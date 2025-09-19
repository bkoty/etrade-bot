
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import ttk, messagebox

from etrade_api import ETradeAPI, SB, PROD
from rotator import OrderRotator

LOGFILE = "rotator.log"

class GuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("E*TRADE Order Rotator")
        self._setup_logging()

        self.env = tk.StringVar(value=PROD)
        self.ckey = tk.StringVar()
        self.csec = tk.StringVar()
        self.pin_req_token = None
        self.pin_req_secret = None
        self.pin_verifier = tk.StringVar()
        self.account_map = {}
        self.selected_account = tk.StringVar()
        self.side_filter = tk.StringVar(value="BOTH")
        self.symbol_filter = tk.StringVar()
        self.dry_run = tk.BooleanVar(value=True)

        # schedule with seconds
        self.s_gtce_1 = tk.StringVar(value="04:01:00")
        self.s_gtce_2 = tk.StringVar(value="16:00:00")
        self.s_extgtc = tk.StringVar(value="19:59:00")

        self.api = None
        self._build_ui()
        self._apply_schedule()

    def _setup_logging(self):
        os.makedirs("logs", exist_ok=True)
        fh = RotatingFileHandler(LOGFILE, maxBytes=1_000_000, backupCount=3)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        rootlog = logging.getLogger()
        rootlog.setLevel(logging.DEBUG)
        rootlog.addHandler(fh)

        # GUI log panel handler
        class TextHandler(logging.Handler):
            def __init__(self, widget): super().__init__(); self.widget=widget
            def emit(self, record):
                msg = self.format(record)
                self.widget.configure(state="normal")
                self.widget.insert("end", msg + "\n")
                self.widget.configure(state="disabled")
                self.widget.see("end")
        self.text_handler = TextHandler
        logging.getLogger().info("Logger initialized.")

    def _build_ui(self):
        # make scrollable frame
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        vscroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")
        self.scroll_canvas = canvas

        # Auth frame
        auth = ttk.LabelFrame(scroll_frame, text="Authentication")
        auth.pack(fill="x", padx=8, pady=6)
        ttk.Label(auth, text="Env:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(auth, text="PROD", variable=self.env, value=PROD).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(auth, text="SB", variable=self.env, value=SB).grid(row=0, column=2, sticky="w")
        ttk.Label(auth, text="Consumer Key").grid(row=1, column=0, sticky="w")
        ttk.Entry(auth, textvariable=self.ckey, width=40).grid(row=1, column=1, columnspan=2, sticky="we", padx=4)
        ttk.Label(auth, text="Consumer Secret").grid(row=2, column=0, sticky="w")
        ttk.Entry(auth, textvariable=self.csec, width=40, show="•").grid(row=2, column=1, columnspan=2, sticky="we", padx=4)

        btns = ttk.Frame(auth)
        btns.grid(row=3, column=0, columnspan=3, sticky="we", pady=4)
        ttk.Button(btns, text="Get PIN Link", command=self._get_pin_link).pack(side="left")
        ttk.Label(btns, text="PIN:").pack(side="left", padx=(12,4))
        ttk.Entry(btns, textvariable=self.pin_verifier, width=10).pack(side="left")
        ttk.Button(btns, text="Submit PIN", command=self._submit_pin).pack(side="left", padx=6)
        ttk.Button(btns, text="Refresh Accounts", command=self._refresh_accounts).pack(side="left", padx=6)

        ttk.Label(auth, text="Account").grid(row=4, column=0, sticky="w")
        self.account_combo = ttk.Combobox(auth, textvariable=self.selected_account, state="readonly", width=40)
        self.account_combo.grid(row=4, column=1, columnspan=2, sticky="we", padx=4)

        # Filters
        flt = ttk.LabelFrame(scroll_frame, text="Filters & Options")
        flt.pack(fill="x", padx=8, pady=6)
        for i, txt in enumerate(("BUY","SELL","BOTH")):
            ttk.Radiobutton(flt, text=txt, value=txt, variable=self.side_filter).grid(row=0, column=i, sticky="w")
        ttk.Label(flt, text="Symbols (comma):").grid(row=1, column=0, sticky="w")
        ttk.Entry(flt, textvariable=self.symbol_filter, width=40).grid(row=1, column=1, columnspan=2, sticky="we", padx=4)
        ttk.Checkbutton(flt, text="Dry-run (no submit)", variable=self.dry_run).grid(row=0, column=3, padx=10)

        # Column filter row
        cf = ttk.Frame(flt)
        cf.grid(row=2, column=0, columnspan=4, sticky="we", pady=(6,0))
        ttk.Label(cf, text="Filter: Symbol").grid(row=0, column=0)
        self.col_sym = tk.StringVar()
        ttk.Entry(cf, textvariable=self.col_sym, width=10).grid(row=0, column=1)
        ttk.Label(cf, text="Type").grid(row=0, column=2)
        self.col_type = tk.StringVar()
        ttk.Entry(cf, textvariable=self.col_type, width=8).grid(row=0, column=3)
        ttk.Label(cf, text="Session").grid(row=0, column=4)
        self.col_sess = tk.StringVar()
        ttk.Entry(cf, textvariable=self.col_sess, width=8).grid(row=0, column=5)
        ttk.Label(cf, text="Qty ≥").grid(row=0, column=6)
        self.col_qty = tk.StringVar()
        ttk.Entry(cf, textvariable=self.col_qty, width=6).grid(row=0, column=7)
        ttk.Label(cf, text="Limit ≥").grid(row=0, column=8)
        self.col_price = tk.StringVar()
        ttk.Entry(cf, textvariable=self.col_price, width=6).grid(row=0, column=9)
        ttk.Button(cf, text="Apply Filters", command=self._apply_column_filters).grid(row=0, column=10, padx=6)

        # Orders table
        tbl = ttk.LabelFrame(scroll_frame, text="Open Orders")
        tbl.pack(fill="both", expand=True, padx=8, pady=6)
        cols = ("chk","orderId","symbol","side","qty","price","priceType","session","duration","placedTime")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", selectmode="extended")
        headings = {
            "chk":"✔", "orderId":"Order ID","symbol":"Symbol","side":"Side","qty":"Qty",
            "price":"Price","priceType":"Type","session":"Session","duration":"Duration","placedTime":"Placed Time"
        }
        for c in cols:
            self.tree.heading(c, text=headings[c], command=lambda c=c: self._sort_by(c, False))
            w = 80
            if c in ("chk","qty"): w=60
            if c in ("orderId","placedTime"): w=120
            if c=="symbol": w=80
            if c=="duration": w=110
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self._toggle_check)

        tb = ttk.Frame(tbl)
        tb.pack(fill="x", pady=4)
        ttk.Button(tb, text="Select All", command=lambda:self._set_all_checks(True)).pack(side="left")
        ttk.Button(tb, text="Select None", command=lambda:self._set_all_checks(False)).pack(side="left", padx=6)
        ttk.Button(tb, text="Preview Open Orders", command=self._preview_orders).pack(side="left", padx=8)

        # Scheduling
        sch = ttk.LabelFrame(scroll_frame, text="Scheduling (HH:MM:SS, America/Phoenix)")
        sch.pack(fill="x", padx=8, pady=6)
        ttk.Label(sch, text="GTC→EXT #1").grid(row=0,column=0,sticky="w"); ttk.Entry(sch,textvariable=self.s_gtce_1,width=10).grid(row=0,column=1)
        ttk.Label(sch, text="GTC→EXT #2").grid(row=0,column=2,sticky="w"); ttk.Entry(sch,textvariable=self.s_gtce_2,width=10).grid(row=0,column=3)
        ttk.Label(sch, text="EXT→GTC").grid(row=0,column=4,sticky="w"); ttk.Entry(sch,textvariable=self.s_extgtc,width=10).grid(row=0,column=5)
        ttk.Button(sch, text="Apply Schedule", command=self._apply_schedule).grid(row=0,column=6,padx=8)

        # Actions
        act = ttk.LabelFrame(scroll_frame, text="Actions")
        act.pack(fill="x", padx=8, pady=6)
        ttk.Button(act, text="Run Now: GTC→EXT", command=lambda:self._run_now("EXTENDED","GOOD_FOR_DAY")).pack(side="left")
        ttk.Button(act, text="Run Now: EXT→GTC", command=lambda:self._run_now("REGULAR","GOOD_UNTIL_CANCEL")).pack(side="left", padx=6)

        # Logs panel
        logf = ttk.LabelFrame(scroll_frame, text="Logs")
        logf.pack(fill="both", expand=True, padx=8, pady=6)
        self.log_text = tk.Text(logf, height=12, state="disabled")
        self.log_text.pack(fill="both", expand=True)
        th = self.text_handler(self.log_text); th.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(th)

    # --- Helpers ---
    def _sort_by(self, col, desc):
        # get data to sort
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        # cast numeric columns
        if col in ("qty","price"):
            def cast(v):
                try: return float(v)
                except: return float("-inf")
            data.sort(key=lambda t: cast(t[0]), reverse=desc)
        else:
            data.sort(key=lambda t: t[0], reverse=desc)
        for i, (_, k) in enumerate(data):
            self.tree.move(k, "", i)
        # toggle next
        self.tree.heading(col, command=lambda c=col: self._sort_by(c, not desc))

    def _toggle_check(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "heading":
            rowid = self.tree.identify_row(event.y)
            col = self.tree.identify_column(event.x)
            if col == "#1":  # chk column
                cur = self.tree.set(rowid, "chk")
                self.tree.set(rowid, "chk", "" if cur=="✓" else "✓")

    def _set_all_checks(self, val: bool):
        for iid in self.tree.get_children(""):
            self.tree.set(iid, "chk", "✓" if val else "")

    def _apply_column_filters(self):
        symf = self.col_sym.get().strip().upper()
        typef = self.col_type.get().strip().upper()
        sessf = self.col_sess.get().strip().upper()
        qtymin = self.col_qty.get().strip()
        pmin = self.col_price.get().strip()
        for iid in self.tree.get_children(""):
            vals = self.tree.item(iid, "values")
            mapping = dict(zip(("chk","orderId","symbol","side","qty","price","priceType","session","duration","placedTime"), vals))
            show = True
            if symf and symf not in str(mapping["symbol"]).upper(): show=False
            if typef and typef not in str(mapping["priceType"]).upper(): show=False
            if sessf and sessf not in str(mapping["session"]).upper(): show=False
            try:
                if qtymin: show = show and (float(mapping["qty"])>=float(qtymin))
                if pmin: show = show and (float(mapping["price"])>=float(pmin))
            except: pass
            if show:
                self.tree.reattach(iid, "", "end")
            else:
                self.tree.detach(iid)

    def _get_pin_link(self):
        try:
            self.api = ETradeAPI(self.ckey.get(), self.csec.get(), env=self.env.get())
            tok, sec, url = self.api.get_request_token()
            self.pin_req_token, self.pin_req_secret = tok, sec
            messagebox.showinfo("Authorize", f"Open this URL, log in, then paste the PIN:\n\n{url}")
        except Exception as e:
            logging.getLogger().exception("Auth init failed")
            messagebox.showerror("Error", f"Auth init failed: {e}")

    def _submit_pin(self):
        try:
            self.api.get_access_token(self.pin_req_token, self.pin_req_secret, self.pin_verifier.get().strip())
            logging.getLogger().info("Access token obtained.")
            self._refresh_accounts()
        except Exception as e:
            logging.getLogger().exception("PIN exchange failed")
            messagebox.showerror("Error", f"PIN exchange failed: {e}")

    def _refresh_accounts(self):
        try:
            accts = self.api.get_accounts()
            self.account_map = {f"{a['name']} ({a['id']})": a["idKey"] for a in accts}
            self.account_combo["values"] = list(self.account_map.keys())
            if accts:
                self.account_combo.current(0)
            logging.getLogger().info("Accounts loaded: %d", len(accts))
        except Exception as e:
            logging.getLogger().exception("Account load failed")
            messagebox.showerror("Error", f"Account load failed: {e}")

    def _preview_orders(self):
        try:
            acct_label = self.selected_account.get()
            if not acct_label:
                messagebox.showwarning("Pick account","Please select an account first.")
                return
            acct_id_key = self.account_map[acct_label]
            rot = OrderRotator(self.api, dry_run=self.dry_run.get())
            orders = rot.preview_open_orders(acct_id_key, self.symbol_filter.get().strip(), self.side_filter.get())
            # fill table
            for i in self.tree.get_children(""):
                self.tree.delete(i)
            for od in orders:
                vals = ["", od.get("orderId"), od.get("symbol"), od.get("side"), od.get("qty"),
                        od.get("price"), od.get("priceType"), od.get("session"), od.get("duration"), od.get("placedTime")]
                self.tree.insert("", "end", values=vals)
            logging.getLogger().info("Preview loaded: %d open orders.", len(orders))
        except Exception as e:
            logging.getLogger().exception("Preview failed")
            messagebox.showerror("Error", f"Preview failed: {e}")

    # Scheduling (simple cron via APScheduler)
    def _apply_schedule(self):
        import pytz
        from tzlocal import get_localzone
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        tz = get_localzone().key if hasattr(get_localzone(), "key") else "America/Phoenix"
        if not hasattr(self, "scheduler"):
            self.scheduler = BackgroundScheduler(timezone=pytz.timezone(tz))
            self.scheduler.start()

        self.scheduler.remove_all_jobs()

        def parse_hms(s):
            h,m,sec = s.split(":")
            return int(h), int(m), int(sec)

        h,m,s = parse_hms(self.s_gtce_1.get())
        self.scheduler.add_job(lambda:self._run_now("EXTENDED","GOOD_FOR_DAY"),
                               CronTrigger(hour=h, minute=m, second=s, timezone=self.scheduler.timezone))
        h,m,s = parse_hms(self.s_gtce_2.get())
        self.scheduler.add_job(lambda:self._run_now("EXTENDED","GOOD_FOR_DAY"),
                               CronTrigger(hour=h, minute=m, second=s, timezone=self.scheduler.timezone))
        h,m,s = parse_hms(self.s_extgtc.get())
        self.scheduler.add_job(lambda:self._run_now("REGULAR","GOOD_UNTIL_CANCEL"),
                               CronTrigger(hour=h, minute=m, second=s, timezone=self.scheduler.timezone))
        logging.getLogger().info("Scheduler updated. GTCE: %s & %s; EXTGTC: %s", self.s_gtce_1.get(), self.s_gtce_2.get(), self.s_extgtc.get())

    def _selected_orders(self):
        sel = []
        for iid in self.tree.get_children(""):
            if self.tree.set(iid, "chk") == "✓":
                od = {k:self.tree.set(iid,k) for k in ("orderId","symbol","side","qty","price","priceType","session","duration")}
                # normalize numbers
                try: od["qty"] = float(od["qty"])
                except: pass
                try: od["price"] = float(od["price"])
                except: pass
                sel.append(od)
        return sel

    def _run_now(self, session, duration):
        try:
            acct_label = self.selected_account.get()
            if not acct_label:
                messagebox.showwarning("Pick account","Please select an account first.")
                return
            acct_id_key = self.account_map[acct_label]
            rot = OrderRotator(self.api, dry_run=self.dry_run.get())
            orders = self._selected_orders()
            if not orders:
                messagebox.showinfo("No orders selected", "Use the ✓ column to pick orders first.")
                return
            import time as _t
            import json as _j
            cnt_ok = 0
            for od in orders:
                if self.dry_run.get():
                    logging.getLogger().info("DRY-RUN %s %s qty=%s (%s → %s) id=%s",
                                             od["side"], od["symbol"], od["qty"], od.get("session"), session, od["orderId"])
                    cnt_ok += 1
                    continue
                # Preview & place
                payload = {"PreviewOrderRequest": {
                    "orderType":"EQ",
                    "clientOrderId": int(_t.time()*1000),
                    "Order":[{
                        "allOrNone": False,
                        "priceType": od.get("priceType","LIMIT"),
                        "orderTerm": duration,
                        "marketSession": session,
                        "Instrument":[{
                            "Product":{"securityType":"EQ","symbol":od["symbol"]},
                            "orderAction": od["side"],
                            "quantityType":"QUANTITY",
                            "quantity": (float(od.get("qty")) if (od.get("qty") not in (None, "", "None")) else (_raise_qty_missing(od))),
                            **({"limitPrice": float(od["price"])} if od.get("price") not in (None,"") else {}),
                        }]
                    }]
                }}
                prev = self.api.preview_change(acct_id_key, od["orderId"], payload)
                # Try to get order-id or previewId if needed; place using same body or include previewId if present
                place_body = {"PlaceOrderRequest": {"orderType":"EQ"}}
                # Some APIs prefer echoing the same 'Order' structure + previewId when returned
                if "PreviewOrderResponse" in prev and "previewId" in prev["PreviewOrderResponse"]:
                    place_body["PlaceOrderRequest"]["previewId"] = prev["PreviewOrderResponse"]["previewId"]
                if "PreviewOrderRequest" in payload:
                    place_body["PlaceOrderRequest"]["Order"] = payload["PreviewOrderRequest"]["Order"]
                plc = self.api.place_change(acct_id_key, od["orderId"], place_body)
                logging.getLogger().info("Changed order %s → %s/%s (resp keys: %s)",
                                         od["orderId"], session, duration, list(plc.keys()))
                cnt_ok += 1
            logging.getLogger().info("Done. Changed %d orders.", cnt_ok)
        except Exception as e:
            logging.getLogger().exception("Run-now failed")
            messagebox.showerror("Error", f"Run-now failed: {e}")

def main():
    root = tk.Tk()
    app = GuiApp(root)
    root.geometry("1000x760")
    root.mainloop()

if __name__ == "__main__":
    main()
