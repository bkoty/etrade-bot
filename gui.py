
import os
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, date, timedelta

from etrade_api import ETradeAPI, PROD, SB

PHX_TZ = "America/Phoenix"  # display-only

class GuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("E*TRADE Rotator with PnL")

        # --- Core state
        self.env = tk.StringVar(value=PROD)
        self.ckey = tk.StringVar()
        self.csec = tk.StringVar()
        self.pin_verifier = tk.StringVar()
        self.selected_account = tk.StringVar()
        self.account_map = {}
        self.api = None
        self._req_token = ""
        self._req_secret = ""

        # --- Orders state
        self.symbol_filter = tk.StringVar()
        self.side_filter = tk.StringVar(value="BOTH")

        # Scheduler
        self.s_gtce_1 = tk.StringVar(value="06:30:00")
        self.s_gtce_2 = tk.StringVar(value="08:00:00")
        self.s_extgtc = tk.StringVar(value="13:00:00")
        self._sched_job_id = None

        # --- PnL state
        self.pnl_symbol = tk.StringVar()
        self.pnl_type = None  # set in UI
        self.pnl_tf = None    # set in UI
        self.pnl_from = tk.StringVar()
        self.pnl_to = tk.StringVar()

        self._setup_logging()
        self._load_config()
        self._build_ui()
        self._arm_scheduler()

    # ---------- Logging to UI ----------
    class TextHandler(logging.Handler):
        def __init__(self, widget: tk.Text):
            super().__init__()
            self.widget = widget
        def emit(self, record):
            try:
                msg = self.format(record)
                self.widget.configure(state="normal")
                self.widget.insert("end", msg + "\\n")
                self.widget.see("end")
                self.widget.configure(state="disabled")
            except Exception:
                pass

    def _setup_logging(self):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # ---------- Config (Desktop JSON) ----------
    def _config_path(self):
        from pathlib import Path
        return str(Path.home() / "Desktop" / "etrade_rotator_config.json")

    def _load_config(self):
        import json
        p = self._config_path()
        try:
            if os.path.exists(p):
                with open(p, "r") as f:
                    cfg = json.load(f)
                self.ckey.set(cfg.get("consumer_key",""))
                self.csec.set(cfg.get("consumer_secret",""))
                logging.info("Loaded keys from %s", p)
        except Exception:
            logging.exception("Failed to load config")

    def _save_config(self):
        import json
        p = self._config_path()
        try:
            with open(p, "w") as f:
                json.dump({"consumer_key": self.ckey.get().strip(),
                           "consumer_secret": self.csec.get().strip()}, f, indent=2)
            logging.info("Saved keys to %s", p)
            messagebox.showinfo("Config", f"Saved to {p}")
        except Exception:
            logging.exception("Failed to save config")
            messagebox.showerror("Config", "Save failed. See logs.")

    # ---------- UI ----------
    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        # ---- Orders tab ----
        tab_orders = ttk.Frame(nb); nb.add(tab_orders, text="Orders")

        auth = ttk.LabelFrame(tab_orders, text="Authentication"); auth.pack(fill="x", padx=8, pady=6)
        ttk.Label(auth, text="Env:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(auth, text="PROD", variable=self.env, value=PROD).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(auth, text="SANDBOX", variable=self.env, value=SB).grid(row=0, column=2, sticky="w")

        ttk.Label(auth, text="Consumer Key").grid(row=1, column=0, sticky="w")
        ttk.Entry(auth, textvariable=self.ckey, width=44).grid(row=1, column=1, sticky="w")
        ttk.Label(auth, text="Consumer Secret").grid(row=2, column=0, sticky="w")
        ttk.Entry(auth, textvariable=self.csec, width=44).grid(row=2, column=1, sticky="w")
        ttk.Button(auth, text="Save Keys", command=self._save_config).grid(row=2, column=2, padx=6)

        btns = ttk.Frame(auth); btns.grid(row=3, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Button(btns, text="Get PIN Link", command=self._get_pin_link).pack(side="left")
        ttk.Label(btns, text="PIN:").pack(side="left", padx=(12,4))
        ttk.Entry(btns, textvariable=self.pin_verifier, width=10).pack(side="left")
        ttk.Button(btns, text="Submit PIN", command=self._submit_pin).pack(side="left", padx=6)
        ttk.Button(btns, text="Refresh Accounts", command=self._refresh_accounts).pack(side="left", padx=6)
        ttk.Button(btns, text="Test API", command=self._test_api).pack(side="left", padx=6)

        ttk.Label(auth, text="Account").grid(row=4, column=0, sticky="w")
        self.account_combo = ttk.Combobox(auth, textvariable=self.selected_account, state="readonly", width=40)
        self.account_combo.grid(row=4, column=1, columnspan=2, sticky="we", pady=2)
        self.account_combo.bind('<<ComboboxSelected>>', self._on_select_account)

        # Filters + controls
        filt = ttk.LabelFrame(tab_orders, text="Filters"); filt.pack(fill="x", padx=8, pady=6)
        ttk.Label(filt, text="Symbol").grid(row=0, column=0, sticky="e")
        ttk.Entry(filt, textvariable=self.symbol_filter, width=10).grid(row=0, column=1, padx=6)
        ttk.Label(filt, text="Side").grid(row=0, column=2, sticky="e")
        self.side_combo = ttk.Combobox(filt, values=["BOTH","BUY","SELL"], textvariable=self.side_filter, state="readonly", width=8)
        self.side_combo.grid(row=0, column=3, padx=6)
        ttk.Button(filt, text="Preview Open Orders", command=self._load_orders).grid(row=0, column=4, padx=8)

        # Orders table
        tbl = ttk.LabelFrame(tab_orders, text="Open Orders"); tbl.pack(fill="both", expand=True, padx=8, pady=6)
        cols = ("orderId","symbol","side","quantity","price","priceType","session","duration","placedTime")
        xbar = ttk.Scrollbar(tbl, orient="horizontal")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", xscrollcommand=xbar.set, selectmode="extended")
        xbar.config(command=self.tree.xview); xbar.pack(side="bottom", fill="x")
        headings = {
            "orderId":"Order ID","symbol":"Symbol","side":"Side","quantity":"Qty",
            "price":"Price","priceType":"Type","session":"Session","duration":"Duration","placedTime":"Placed Time"
        }
        for c in cols:
            self.tree.heading(c, text=headings[c], command=lambda c=c: self._sort_tree(self.tree, c))
            w = 100 if c in ("orderId","placedTime") else 90 if c in ("priceType","duration","session") else 80
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True)

        # Selection buttons
        sel = ttk.Frame(tab_orders); sel.pack(fill="x", padx=8, pady=4)
        ttk.Button(sel, text="Select All", command=lambda:self._select_all(self.tree, True)).pack(side="left")
        ttk.Button(sel, text="Select None", command=lambda:self._select_all(self.tree, False)).pack(side="left", padx=6)

        # Scheduler + Run Now
        sch = ttk.LabelFrame(tab_orders, text=f"Scheduling (HH:MM:SS, {PHX_TZ})"); sch.pack(fill="x", padx=8, pady=6)
        ttk.Label(sch, text="GTC→EXT #1").grid(row=0, column=0, sticky="e")
        ttk.Entry(sch, textvariable=self.s_gtce_1, width=10).grid(row=0, column=1)
        ttk.Label(sch, text="GTC→EXT #2").grid(row=0, column=2, sticky="e")
        ttk.Entry(sch, textvariable=self.s_gtce_2, width=10).grid(row=0, column=3)
        ttk.Label(sch, text="EXT→GTC").grid(row=0, column=4, sticky="e")
        ttk.Entry(sch, textvariable=self.s_extgtc, width=10).grid(row=0, column=5)
        ttk.Button(sch, text="Apply Schedule", command=self._arm_scheduler).grid(row=0, column=6, padx=8)

        act = ttk.LabelFrame(tab_orders, text="Actions"); act.pack(fill="x", padx=8, pady=6)
        ttk.Button(act, text="Run Now: GTC→EXT", command=lambda:self._run_now("EXTENDED","GOOD_FOR_DAY")).pack(side="left")
        ttk.Button(act, text="Run Now: EXT→GTC", command=lambda:self._run_now("REGULAR","GOOD_UNTIL_CANCEL")).pack(side="left", padx=6)

        # ---- PnL tab ----
        tab_pnl = ttk.Frame(nb); nb.add(tab_pnl, text="PnL")
        pnl_top = ttk.LabelFrame(tab_pnl, text="Filters"); pnl_top.pack(fill="x", padx=8, pady=6)
        ttk.Label(pnl_top, text="Symbol").grid(row=0, column=0, sticky="e")
        ttk.Entry(pnl_top, textvariable=self.pnl_symbol, width=12).grid(row=0, column=1, padx=6)
        ttk.Label(pnl_top, text="Type").grid(row=0, column=2, sticky="e")
        self.pnl_type = ttk.Combobox(pnl_top, values=["All","Stocks","Options"], state="readonly", width=10); self.pnl_type.current(0); self.pnl_type.grid(row=0, column=3, padx=6)
        ttk.Label(pnl_top, text="Timeframe").grid(row=0, column=4, sticky="e")
        self.pnl_tf = ttk.Combobox(pnl_top, values=["Today","This Week","This Month","YTD","1 Year","2 Years","3 Years","5 Years","Custom"], state="readonly", width=12); self.pnl_tf.current(3); self.pnl_tf.grid(row=0, column=5, padx=6)
        ttk.Label(pnl_top, text="From").grid(row=1, column=0, sticky="e")
        ttk.Entry(pnl_top, textvariable=self.pnl_from, width=12).grid(row=1, column=1, padx=6)
        ttk.Label(pnl_top, text="To").grid(row=1, column=2, sticky="e")
        ttk.Entry(pnl_top, textvariable=self.pnl_to, width=12).grid(row=1, column=3, padx=6)
        ttk.Button(pnl_top, text="Load PnL", command=self._load_pnl).grid(row=1, column=5, padx=6)

        pnl_tbl = ttk.LabelFrame(tab_pnl, text="Realized PnL"); pnl_tbl.pack(fill="both", expand=True, padx=8, pady=6)
        self.pnl_tree = ttk.Treeview(pnl_tbl, columns=("symbol","type","trades","qty_buy","qty_sell","realized","fees","start","end"), show="headings")
        for c, h, w in [("symbol","Symbol",100),("type","Type",80),("trades","Trades",80),("qty_buy","Buy Qty",80),("qty_sell","Sell Qty",80),("realized","Realized $",110),("fees","Fees",80),("start","Start",110),("end","End",110)]:
            self.pnl_tree.heading(c, text=h, command=lambda c=c: self._sort_tree(self.pnl_tree, c))
            self.pnl_tree.column(c, width=w, anchor="center")
        self.pnl_tree.pack(fill="both", expand=True)
        pnl_tot = ttk.Frame(tab_pnl); pnl_tot.pack(fill="x", padx=8, pady=4)
        self.pnl_total_label = ttk.Label(pnl_tot, text="Total Realized: $0.00"); self.pnl_total_label.pack(side="left")




        # ---- Day Trades tab ----
        tab_day = ttk.Frame(nb); nb.add(tab_day, text="Day Trades")
        day_top = ttk.Frame(tab_day); day_top.pack(fill="x", padx=8, pady=6)
        ttk.Button(day_top, text="Refresh Today", command=self._load_day_trades).pack(side="left", padx=6)
        day_cols = ("Time","Symbol","Side","Qty","Price","Gross","Fees","Net","Order ID")
        self.day_trades_tree = ttk.Treeview(tab_day, columns=day_cols, show="headings", height=14)
        for c in day_cols:
            self.day_trades_tree.heading(c, text=c, command=lambda c=c: self._sort_tree(self.day_trades_tree, c))
            self.day_trades_tree.column(c, anchor="center", width=100)
        self.day_trades_tree.pack(fill="both", expand=True, padx=8, pady=(0,6))

        # ---- Logs tab ----
        tab_logs = ttk.Frame(nb); nb.add(tab_logs, text="Logs")
        logf = ttk.LabelFrame(tab_logs, text="Logs"); logf.pack(fill="both", expand=True, padx=8, pady=6)
        log_xbar = ttk.Scrollbar(logf, orient="horizontal")
        self.log_text = tk.Text(logf, height=20, state="disabled", wrap="none", xscrollcommand=log_xbar.set)
        log_xbar.config(command=self.log_text.xview); self.log_text.pack(fill="both", expand=True); log_xbar.pack(side="bottom", fill="x")
        th = self.TextHandler(self.log_text); th.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(th)

    # ---------- Auth ----------
    def _get_pin_link(self):
        import webbrowser
        try:
            self.api = ETradeAPI(self.ckey.get().strip(), self.csec.get().strip(), self.env.get().strip())
            res = self.api.get_request_token()
            rtok = rsec = None
            auth_url = None
            if isinstance(res, dict):
                rtok = res.get("request_token") or res.get("oauth_token") or res.get("token")
                rsec = res.get("request_token_secret") or res.get("oauth_token_secret") or res.get("token_secret")
                auth_url = res.get("authorize_url") or res.get("auth_url") or res.get("url")
                for v in res.values():
                    if isinstance(v, str) and v.startswith(("http://","https://")):
                        auth_url = v; break
            elif isinstance(res, (tuple, list)):
                for v in res:
                    if isinstance(v, str) and v.startswith(("http://","https://")):
                        auth_url = v
                    elif isinstance(v, str):
                        if rtok is None: rtok = v
                        elif rsec is None: rsec = v
            elif isinstance(res, str) and res.startswith(("http://","https://")):
                auth_url = res
            if not auth_url and rtok:
                auth_url = f"https://us.etrade.com/e/t/etws/authorize?key={self.ckey.get().strip()}&token={rtok}"
            self._req_token = rtok or getattr(self.api, "request_token", "")
            self._req_secret = rsec or getattr(self.api, "request_token_secret", "")
            if not auth_url:
                messagebox.showerror("Authorize", "Failed to obtain authorization URL."); return
            try: webbrowser.open(auth_url)
            except Exception: pass
            messagebox.showinfo("Authorize", f"Open this URL, authorize, and paste the PIN:\\n\\n{auth_url}")
        except Exception as e:
            logging.exception("Get PIN Link failed")
            messagebox.showerror("Error", str(e))

    def _submit_pin(self):
        if not self.api:
            messagebox.showerror("Error", "Click 'Get PIN Link' first.")
            return
        try:
            pin = self.pin_verifier.get().strip()
            rtok = self._req_token or getattr(self.api, "request_token", "")
            rsec = self._req_secret or getattr(self.api, "request_token_secret", "")
            if not rtok or not rsec:
                messagebox.showwarning("Warning", "Request token not captured. Click 'Get PIN Link' again and re-authorize."); return
            try:
                self.api.get_access_token(rtok, rsec, pin)
            except TypeError:
                self.api.get_access_token(pin)
            messagebox.showinfo("Authorized", "Access token received.")
        except Exception as e:
            logging.exception("Submit PIN failed")
            messagebox.showerror("Error", str(e))

    # ---------- Test API ----------
    def _test_api(self):
        try:
            if not self.api:
                self.api = ETradeAPI(self.ckey.get().strip(), self.csec.get().strip(), self.env.get().strip())
            acct_label = self.selected_account.get().strip()
            acct_key = self.account_map.get(acct_label) or self.account_map.get(acct_label.split(" ")[0]) or acct_label
            logging.info("[TEST] Using account key: %s", acct_key)
            o = self._fetch_orders_fallback(acct_key)
            t = self._fetch_transactions_fallback(acct_key, date.today()-timedelta(days=30), date.today(), None, 50)
            messagebox.showinfo("API Test", f"Orders fetched: {len(o)}\\nTransactions fetched: {len(t)}")
        except Exception as e:
            logging.exception("API test failed")
            messagebox.showerror("API Test", str(e))

    # ---------- Accounts ----------
    def _fallback_fetch_accounts(self):
        try:
            # Coerce start/end to dates if strings
            try:
                if isinstance(start, str):
                    start = dt.datetime.strptime(start, '%Y-%m-%d').date() if '-' in start else dt.datetime.strptime(start, '%m/%d/%Y').date()
                if isinstance(end, str):
                    end = dt.datetime.strptime(end, '%Y-%m-%d').date() if '-' in end else dt.datetime.strptime(end, '%m/%d/%Y').date()
            except Exception:
                pass
            env = (self.env.get() or "").strip().upper()
            base = "https://api.etrade.com" if env == "PROD" else "https://apisb.etrade.com"
            url = f"{base}/v1/accounts/list.json"
            sess = getattr(self.api, "session", None)
            if not sess: return []
            resp = sess.get(url, headers={"Accept":"application/json"})
            if resp.status_code != 200:
                logging.error("Fallback accounts GET %s → %s %s", url, resp.status_code, resp.text[:200]); return []
            try: data = resp.json()
            except Exception: logging.error("Fallback accounts: non-JSON response"); return []
            node = data.get("AccountListResponse") or data.get("accounts") or data
            if isinstance(node, dict): node = node.get("Accounts") or node.get("accounts") or node
            if isinstance(node, dict): node = node.get("Account") or node.get("account") or node
            if isinstance(node, dict): node = [node]
            if not isinstance(node, list): return []
            out = []
            for a in node:
                if not isinstance(a, dict): continue
                out.append({
                    "accountId": str(a.get("accountId") or a.get("accountIdKey") or a.get("accountIdMasked") or ""),
                    "accountIdKey": str(a.get("accountIdKey") or a.get("accountId") or ""),
                    "accountDesc": str(a.get("accountDesc") or a.get("displayName") or a.get("name") or ""),
                })
            return out
        except Exception:
            logging.exception("Fallback accounts failed")
            return []

    def _on_select_account(self, event=None):
        try:
            label = (self.selected_account.get() or "").strip()
            key = self.account_map.get(label) or (label.split(" ")[0] if label else "")
            if key:
                self.account_id_key = key
                logging.info("Selected account key set: %s", key)
        except Exception:
            logging.exception("Failed to set selected account")

    def _refresh_accounts(self):
        try:
            if not self.api:
                self.api = ETradeAPI(self.ckey.get().strip(), self.csec.get().strip(), self.env.get().strip())
            accts = []
            try:
                accts = self.api.get_accounts() or []
            except Exception as inner_e:
                logging.error("Primary get_accounts failed: %s", inner_e)
            if not accts:
                accts = self._fallback_fetch_accounts() or []
            labels = []
            self.account_map.clear()
            for a in accts:
                label = f"{a.get('accountId')}  ({a.get('accountDesc','')})"
                labels.append(label)
                self.account_map[label] = a.get("accountIdKey") or a.get("accountId")
            self.account_combo["values"] = labels
            if labels and not self.selected_account.get():
                self.selected_account.set(labels[0])
                self._on_select_account()
                self._on_select_account()
            if labels:
                logging.info("Loaded %d accounts", len(labels))
            else:
                logging.warning("No accounts were returned by API")
                messagebox.showwarning("Accounts", "No accounts were returned. If you have multiple profiles, try again shortly.")
        except Exception as e:
            logging.exception("Accounts refresh failed")
            messagebox.showerror("Error", str(e))

    # ---------- Deep order parsing helpers ----------
    def _deep_get_first(self, obj, keys):
        """Search dict/list recursively and return the first non-empty value for any of keys."""
        seen = set()
        def dfs(o):
            if id(o) in seen: 
                return None
            seen.add(id(o))
            if isinstance(o, dict):
                for k in keys:
                    if k in o and o[k] not in (None, "", []):
                        return o[k]
                for v in o.values():
                    res = dfs(v)
                    if res not in (None, "", []):
                        return res
            elif isinstance(o, list):
                for v in o:
                    res = dfs(v)
                    if res not in (None, "", []):
                        return res
            return None
        return dfs(obj)

    def _order_rows_from_payload(self, order_obj):
        """Yield normalized rows from a raw order object; handles nested OrderDetail/Instrument structures."""
        details = order_obj.get("OrderDetail") or order_obj.get("orderDetail") or order_obj.get("orderDetails") or None
        if isinstance(details, dict):
            details = [details]
        if isinstance(details, list) and details:
            for d in details:
                yield self._normalize_order_row(order_obj, d)
        else:
            yield self._normalize_order_row(order_obj, None)

    def _normalize_order_row(self, order_obj, detail_obj=None):
        order_id = (order_obj.get("orderId") or order_obj.get("id") or 
                    self._deep_get_first(order_obj, ["orderId","id","orderNumber","clordId"]) or "")
        symbol = (self._deep_get_first(detail_obj or order_obj, ["symbol","productSymbol","securitySymbol"]) or "")
        if not symbol:
            prod = self._deep_get_first(detail_obj or order_obj, ["Product","product","Instrument","instrument"])
            if isinstance(prod, dict):
                symbol = prod.get("symbol") or prod.get("securitySymbol") or ""
            elif isinstance(prod, list):
                for it in prod:
                    if isinstance(it, dict):
                        symbol = it.get("symbol") or it.get("securitySymbol") or ""
                        if symbol: break
        symbol = (str(symbol).upper() if symbol else "")
        side = (self._deep_get_first(detail_obj or order_obj, ["orderAction","transactionType","side","instruction","OrderAction"]) or "")
        side = str(side).upper()
        qty = (self._deep_get_first(detail_obj or order_obj, ["orderedQuantity","quantity","qty","filledQuantity"]) or "")
        try:
            if isinstance(qty, str) and qty.strip() == "": qty = ""
            elif qty not in ("", None): qty = float(qty)
        except Exception:
            pass
        price = (self._deep_get_first(detail_obj or order_obj, ["price","limitPrice","avgExecPrice","stopPrice","stopLimitPrice"]) or "")
        try:
            if isinstance(price, str) and price.strip() == "": price = ""
            elif price not in ("", None): price = float(price)
        except Exception:
            pass
        price_type = (self._deep_get_first(detail_obj or order_obj, ["priceType","orderType"]) or "")
        session = (self._deep_get_first(detail_obj or order_obj, ["session","marketSession"]) or "")
        duration = (self._deep_get_first(detail_obj or order_obj, ["duration","orderTerm"]) or "")
        placed = (self._deep_get_first(order_obj, ["placedTime","orderTime","timePlaced","placeTime"]) or "")
        return (order_id, symbol, side, qty, price, price_type, session, duration, placed)

    # ---------- Orders ----------
    def _fetch_orders_fallback(self, acct_key):
        try:
            # Coerce start/end to dates if strings
            try:
                if isinstance(start, str):
                    start = dt.datetime.strptime(start, '%Y-%m-%d').date() if '-' in start else dt.datetime.strptime(start, '%m/%d/%Y').date()
                if isinstance(end, str):
                    end = dt.datetime.strptime(end, '%Y-%m-%d').date() if '-' in end else dt.datetime.strptime(end, '%m/%d/%Y').date()
            except Exception:
                pass
            env = (self.env.get() or "").strip().upper()
            base = "https://api.etrade.com" if env == "PROD" else "https://apisb.etrade.com"
            sess = getattr(self.api, "session", None)
            if not sess:
                logging.error("No session available for orders fallback"); return []
            endpoints = [
                f"{base}/v1/accounts/{acct_key}/orders.json",
                f"{base}/v1/accounts/{acct_key}/orders",
                f"{base}/v1/accounts/{acct_key}/orders/",
            ]
            param_sets = [
                {"status":"OPEN", "detailFlag":"ALL", "fromDate": (date.today()-timedelta(days=30)).strftime("%m%d%Y")},
                {"status":"OPEN", "detailFlag":"ALL"},
                {"status":"OPEN"},
                {}
            ]
            headers_list = [
                {"Accept":"application/json"},
                {"Accept":"application/json", "Content-Type":"application/json"}
            ]
            for url in endpoints:
                for params in param_sets:
                    for hdrs in headers_list:
                        try:
                            resp = sess.get(url, params=params, headers=hdrs)
                            logging.info("Orders try: %s ? %s -> %s", url, params, resp.status_code)
                            if resp.status_code != 200:
                                continue
                            try:
                                data = resp.json()
                            except Exception:
                                continue
                            node = (data.get("OrdersResponse") or data.get("orders") or
                                    data.get("OrderListResponse") or data)
                            if isinstance(node, dict):
                                node = node.get("Order") or node.get("orders") or node.get("order") or node
                            if isinstance(node, dict):
                                node = [node]
                            if isinstance(node, list) and node:
                                return node
                        except Exception as e:
                            logging.error("Orders fetch error on %s: %s", url, e)
            logging.warning("Orders fallback returned no data after tries")
            return []
        except Exception:
            logging.exception("Orders fallback failed")
            return []

    def _load_orders(self):
        try:
            acct_label = self.selected_account.get().strip()
            acct_key = self.account_map.get(acct_label) or self.account_map.get(acct_label.split(" ")[0]) or acct_label
            if not acct_key:
                messagebox.showerror("Orders", "No account selected. Refresh Accounts first."); return
            orders = []
            if hasattr(self.api, "get_open_orders"):
                try:
                    orders = self.api.get_open_orders(acct_key) or []
                except Exception as e:
                    logging.error("Primary get_open_orders failed: %s", e)
            if not orders:
                orders = self._fetch_orders_fallback(acct_key) or []

            # Filters
            symf = (self.symbol_filter.get() or "").strip().upper()
            sidef = (self.side_filter.get() or "BOTH").upper()

            for iid in self.tree.get_children(""): self.tree.delete(iid)
            inserted = 0
            for o in orders:
                try:
                    rows = list(self._order_rows_from_payload(o))
                except Exception:
                    rows = []
                if not rows:
                    rows = [self._normalize_order_row(o, None)]
                for row in rows:
                    order_id, symbol, side, qty, price, price_type, session, duration, placed = row
                    if symf and symbol != symf:
                        continue
                    if sidef != "BOTH" and side != sidef:
                        continue
                    self.tree.insert("", "end", values=(order_id, symbol, side, qty, price, price_type, session, duration, placed))
                    inserted += 1
            logging.info("Loaded %d open orders for %s", inserted, acct_label)
        except Exception as e:
            logging.exception("Orders load failed")
            messagebox.showerror("Orders", f"Failed to load orders: {e}")

    def _sort_tree(self, tree, col):
        try:
            data = [(tree.set(k, col), k) for k in tree.get_children("")]
            def coerce(x):
                try: return float(str(x).replace(",","").replace("$",""))
                except: return str(x)
            data.sort(key=lambda t: coerce(t[0]))
            for i, (_, k) in enumerate(data):
                tree.move(k, "", i)
        except Exception:
            pass

    def _select_all(self, tree, flag: bool):
        items = tree.get_children("")
        if flag: tree.selection_set(items)
        else: tree.selection_remove(items)

    # ---------- Scheduler & Actions ----------
    def _arm_scheduler(self):
        if self._sched_job_id is not None:
            try:
                self.root.after_cancel(self._sched_job_id)
            except Exception:
                pass
            self._sched_job_id = None
        logging.info("Scheduler armed: GTC→EXT at %s and %s; EXT→GTC at %s (%s)",
                     self.s_gtce_1.get(), self.s_gtce_2.get(), self.s_extgtc.get(), PHX_TZ)
        self._tick_scheduler()

    def _tick_scheduler(self):
        try:
            now = datetime.now().strftime("%H:%M:%S")
            if now == self.s_gtce_1.get().strip() or now == self.s_gtce_2.get().strip():
                self._run_now("EXTENDED","GOOD_FOR_DAY")
            if now == self.s_extgtc.get().strip():
                self._run_now("REGULAR","GOOD_UNTIL_CANCEL")
        finally:
            self._sched_job_id = self.root.after(1000, self._tick_scheduler)

    def _run_now(self, session: str, duration: str):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Actions", "Select one or more orders first."); return
        picked = [self.tree.item(i)["values"] for i in sel]
        logging.info("Would update %d orders to session=%s duration=%s (simulate).", len(picked), session, duration)
        # Hook to real API replace/update if available.

    # ---------- PnL ----------
    def _tf_to_range(self, tf: str, custom_from: str = "", custom_to: str = ""):
        today = date.today()
        start = end = today
        tf = (tf or "").lower()
        if tf in ("today",):
            start = end = today
        elif tf in ("this week","week"):
            start = today - timedelta(days=today.weekday()); end = today
        elif tf in ("this month","month"):
            start = today.replace(day=1); end = today
        elif tf in ("ytd","year to date"):
            start = today.replace(month=1, day=1); end = today
        elif "year" in tf:
            n = int(tf.split()[0])
            try: start = today.replace(year=today.year - n)
            except ValueError: start = today.replace(month=2, day=28, year=today.year - n)
            end = today
        elif tf == "custom":
            try:
                if custom_from: start = datetime.strptime(custom_from, "%Y-%m-%d").date()
                if custom_to: end = datetime.strptime(custom_to, "%Y-%m-%d").date()
            except Exception: pass
        return start, end

    
    def _fetch_transactions_fallback(self, acct_key, start, end, symbol=None, count=500):
        """Fallback HTTP getter for /transactions when API wrapper lacks get_transactions."""
        import datetime as _dt

        # Coerce to dates if strings
        try:
            if isinstance(start, str):
                start = _dt.datetime.strptime(start, "%Y-%m-%d").date() if "-" in start else _dt.datetime.strptime(start, "%m/%d/%Y").date()
            if isinstance(end, str):
                end = _dt.datetime.strptime(end, "%Y-%m-%d").date() if "-" in end else _dt.datetime.strptime(end, "%m/%d/%Y").date()
        except Exception:
            start = _dt.date.today(); end = _dt.date.today()

        try:
            env = (self.env.get() or "").strip().upper()
            base = "https://api.etrade.com" if env == "PROD" else "https://apisb.etrade.com"
            sess = getattr(self.api, "session", None)
            if not sess:
                logging.error("No session available for transactions fallback"); return []

            endpoints = [
                f"{base}/v1/accounts/{acct_key}/transactions",
                f"{base}/v1/accounts/{acct_key}/transactions.json",
                f"{base}/v1/accounts/{acct_key}/transactions/",
            ]
            def mmddyyyy(d): return d.strftime("%m%d%Y")
            param_sets = [
                {},  # safest
                {"count": int(count)},
                {"startDate": mmddyyyy(start), "endDate": mmddyyyy(end), "count": int(count)},
            ]
            if symbol:
                param_sets[1]["symbol"] = symbol
                param_sets[2]["symbol"] = symbol

            headers = {"Accept":"application/json"}
            def _row_date(t):
                v = t.get("transactionDate") or t.get("tradeDate") or t.get("time") or t.get("date")
                if not v: return None
                try:
                    v = str(v)
                    if "T" in v and "-" in v:
                        return _dt.datetime.fromisoformat(v.split(".")[0]).date()
                    if "/" in v and len(v.split("/")[-1]) == 4:
                        return _dt.datetime.strptime(v, "%m/%d/%Y").date()
                    if "-" in v and len(v.split("-")[0]) == 4:
                        return _dt.datetime.strptime(v, "%Y-%m-%d").date()
                except Exception:
                    return None
                return None

            for url in endpoints:
                for params in param_sets:
                    try:
                        logging.info("Txns try: %s ? %s", url, params)
                        r = sess.get(url, params=params, headers=headers)
                        if r.status_code == 200:
                            data = r.json() or {}
                            txns = ((data.get("TransactionListResponse") or {}).get("Transaction")
                                    or data.get("Transaction") or [])
                            # client filter
                            txns = [t for t in txns if ((d:=_row_date(t)) is None or (start <= d <= end))]
                            return txns
                    except Exception as e:
                        logging.error("Txns try failed: %s", e)
            return []
        except Exception:
            logging.exception("Fallback transactions failed")
            return []

    
    
    def _load_day_trades(self):
        """Load today's fills/transactions and populate the Day Trades table."""
        try:
            tree = getattr(self, "day_trades_tree", None)
            if tree:
                for iid in tree.get_children():
                    tree.delete(iid)

            # Ensure account key
            label = (self.selected_account.get() or "").strip()
            acct_key = self.account_map.get(label) or (label.split(" ")[0] if label else "")
            if acct_key:
                self.account_id_key = acct_key
            if not getattr(self, "api", None) or not getattr(self, "account_id_key", None):
                logging.warning("Day Trades: API or account not ready")
                return

            today = date.today()
            start = today  # pass date objects, not strings
            end = today

            rows = []
            if hasattr(self.api, "get_transactions"):
                rows = self.api.get_transactions(self.account_id_key, start, end) or []
            else:
                rows = self._fetch_transactions_fallback(self.account_id_key, start, end) or []

            total_trades = 0; total_qty = 0.0; total_gross = 0.0; total_fees = 0.0
            for t in rows:
                ts = t.get("time") or t.get("transactionDate") or t.get("tradeDate") or ""
                sym = (t.get("symbol") or t.get("productSymbol") or t.get("securitySymbol") or t.get("symbolDescription") or "")
                side = t.get("side") or t.get("transactionType") or ""
                qty = float(t.get("quantity") or t.get("shares") or 0)
                price = float(t.get("price") or t.get("averagePrice") or 0)
                gross = float(t.get("proceeds") or t.get("amount") or 0)
                fees = float(t.get("fees") or t.get("commission") or 0)
                net = gross - fees
                if tree:
                    tree.insert("", "end", values=(ts, sym, side, qty, price, gross, fees, net, t.get("orderId") or t.get("transactionId") or ""))
                total_trades += 1; total_qty += qty; total_gross += gross; total_fees += fees
            if tree:
                tree.insert("", "end", values=("", "", "TOTAL", total_qty, "", total_gross, total_fees, total_gross-total_fees, f"{total_trades} trades"))
        except Exception:
            logging.exception("Day Trades load failed")


    def _load_pnl(self):
        try:
            acct_label = self.selected_account.get().strip()
            acct_key = self.account_map.get(acct_label) or self.account_map.get(acct_label.split(" ")[0]) or acct_label
            if not acct_key:
                messagebox.showerror("PnL", "No account selected. Go to Orders tab and select an account first."); return
        except Exception:
            messagebox.showerror("PnL", "No account selected. Go to Orders tab and select an account first."); return

        tf = self.pnl_tf.get(); s_from = self.pnl_from.get().strip(); s_to = self.pnl_to.get().strip()
        start, end = self._tf_to_range(tf, s_from, s_to)
        symbol = (self.pnl_symbol.get() or "").strip().upper() or None
        typ = self.pnl_type.get()

        # Try API get_transactions first; else fallback
        txns = []
        try:
            if not self.api:
                self.api = ETradeAPI(self.ckey.get().strip(), self.csec.get().strip(), self.env.get().strip())
            if hasattr(self.api, "get_transactions"):
                txns = self.api.get_transactions(acct_key, start=start, end=end, symbol=symbol, count=500) or []
            else:
                txns = self._fetch_transactions_fallback(acct_key, start, end, symbol=symbol, count=500) or []
        except Exception as e:
            logging.exception("PnL load failed")
            messagebox.showerror("PnL", f"PnL load failed: {e}"); return

        from collections import defaultdict
        agg = defaultdict(lambda: {"symbol":"","type":"Stocks","trades":0,"qty_buy":0.0,"qty_sell":0.0,"realized":0.0,"fees":0.0,"start":start.isoformat(),"end":end.isoformat()})

        def g(d, *keys):
            for k in keys:
                if isinstance(d, dict) and k in d and d[k] is not None: return d[k]
            return None

        for t in txns or []:
            desc = (g(t,"description") or g(t.get("transaction",{}),"description") or "")
            sym = g(t,"symbol","securitySymbol","ticker","productSymbol") or g(t.get("transaction",{}),"symbol","securitySymbol","ticker")
            if not sym:
                for token in str(desc).replace(","," ").split():
                    if token.isalpha() and token.isupper() and 1 <= len(token) <= 5: sym = token; break
            sym = (sym or "UNKNOWN").upper()

            sec_type = (str(g(t,"productType","securityType","instrumentType") or g(t.get("transaction",{}),"productType","securityType","instrumentType") or "")).lower()
            ttype = "Options" if ("option" in sec_type or " call " in desc.lower() or " put " in desc.lower()) else "Stocks"
            if typ != "All" and ttype != typ: continue

            side = (str(g(t,"transactionType","type","action") or g(t.get("transaction",{}),"transactionType","type","action") or "")).lower()
            if not side:
                sd = desc.lower()
                if "sell" in sd: side = "sell"
                elif "buy" in sd or "bought" in sd: side = "buy"

            qty = 0.0
            for k in ("quantity","qty","shares"):
                v = g(t,k) or g(t.get("transaction",{}),k)
                if v is not None:
                    try: qty = float(v); break
                    except: pass

            amt = None
            for k in ("netAmount","netamount","net","amount"):
                v = g(t,k) or g(t.get("transaction",{}),k)
                if v is not None:
                    try: amt = float(v); break
                    except: pass
            if amt is None and qty:
                price = None
                for k in ("price","avgPrice","averagePrice"):
                    v = g(t,k) or g(t.get("transaction",{}),k)
                    if v is not None:
                        try: price = float(v); break
                        except: pass
                if price is not None:
                    amt = price * qty if side == "sell" else -price * qty
            if amt is None: amt = 0.0

            fees = 0.0
            for k in ("fees","commission","fee"):
                v = g(t,k) or g(t.get("transaction",{}),k)
                if v is not None:
                    try: fees = float(v); break
                    except: pass

            a = agg[(sym, ttype)]
            a["symbol"] = sym
            a["type"] = ttype
            a["trades"] += 1
            if side == "buy":
                a["qty_buy"] += qty; a["realized"] -= abs(amt)
            elif side == "sell":
                a["qty_sell"] += qty; a["realized"] += abs(amt)
            a["fees"] += fees

        for iid in self.pnl_tree.get_children(""): self.pnl_tree.delete(iid)
        total = 0.0
        for (sym, ttype), a in sorted(agg.items()):
            realized = a["realized"] - a["fees"]; total += realized
            self.pnl_tree.insert("", "end", values=(sym, ttype, a["trades"], f"{a['qty_buy']:.0f}", f"{a['qty_sell']:.0f}", f"{realized:.2f}", f"{a['fees']:.2f}", a["start"], a["end"]))
        self.pnl_total_label.config(text=f"Total Realized: ${total:.2f}")
        logging.info("PnL loaded for %s (%s → %s)", acct_label, start, end)

def main():
    root = tk.Tk()
    app = GuiApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
