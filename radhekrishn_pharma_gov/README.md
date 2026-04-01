# radhekrishn_pharma_gov — Odoo Custom Addon
## Government Pharma Supply Management for Radhekrishn Biotech

---

## What this module does

- **Institutions master**: AP ESI, TG ESI, APSMIDC, TSMSIDC, DHS Goa, CGHS, Defence — pre-loaded
- **Rate Contract register**: All 12 products from your claim sheet — pre-loaded with rates, margins, penalties
- **6-stage PO pipeline**: Received → Forwarded → Dispatched → QC Cleared → Institution Paid → Closed
- **Auto-calculations**: Supply due date, delay weeks, supply penalty (2%/wk, max 10%), claim interest (0.5%/wk after 90/120 days)
- **Commission invoice**: One-click to generate Sale Order to vendor for commission amount
- **Kanban pipeline view**: See all POs visually by stage
- **Alerts**: Separate menu for overdue supply POs and pending commission

---

## Installation Steps

### Step 1 — Copy module to Odoo addons folder

```bash
cp -r radhekrishn_pharma_gov /path/to/odoo/addons/
```

Common paths:
- Odoo installed via pip: `/usr/lib/python3/dist-packages/odoo/addons/`
- Custom addons folder: wherever your `addons_path` points in `odoo.conf`

### Step 2 — Update addons list

```bash
# Restart Odoo service
sudo systemctl restart odoo

# Or from command line
python3 odoo-bin -d YOUR_DB_NAME -u radhekrishn_pharma_gov --stop-after-init
```

### Step 3 — Install from Odoo UI

1. Go to **Settings → Activate developer mode**
2. Go to **Apps → Update Apps List**
3. Search for **Radhekrishn Pharma Gov Supply**
4. Click **Install**

---

## Post-installation: Fix vendor references in RC data

The XML data file uses `ref="base.res_partner_1"` as a placeholder for all vendors.
After installation, open each Rate Contract record and set the correct vendor:

| RC Records | Vendor to set |
|------------|--------------|
| rc_169_calcium_os, rc_169_calcium_fd, rc_7ek tablets, rc_169_diclofenac_apsmidc | Midas Care |
| rc_169_antioxidant_ajantha | Ajantha Pharma |
| rc_169_astyfer_tsmsidc | Tablets India |

Also set the **Institution** many2many field on each RC record.

### Correct way (no manual editing)

Create vendors first via **Contacts → Create** with type = Vendor, then re-run data import:
```bash
python3 odoo-bin -d YOUR_DB_NAME -i radhekrishn_pharma_gov --stop-after-init
```

---

## Creating a new PO (day-to-day usage)

1. Go to **Govt Supply → PO Pipeline**
2. Click **New**
3. Fill: Institution, RC Agreement (auto-fills vendor), PO Number, PO Approval Date
4. Add order lines with products and quantities at RC rate
5. Set **Vendor Acceptance Date** (PO approval + 7 days) → supply due date auto-calculates
6. Attach scanned PO copy via chatter / attachment
7. Click **Mark Forwarded** → email vendor
8. When vendor dispatches: fill Dispatch tab (LR No, batch, expiry) → **Mark Dispatched**
9. When QC clears: fill QC tab → **Mark QC Cleared**
10. When institution pays: fill Institution Payment tab → **Mark Institution Paid**
11. Click **Generate Commission Invoice** → Sale Order created to vendor
12. When commission received: fill Commission tab → **Close PO**

---

## Odoo version compatibility

- Tested structure: **Odoo 16.0 and 17.0**
- For Odoo 14 or 15: change `decoration-*` attributes on list views to `attrs` syntax

---

## Files in this module

```
radhekrishn_pharma_gov/
├── __manifest__.py              # Module metadata
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── institution.py           # rk.institution model
│   ├── rc_agreement.py          # rk.rc.agreement model
│   └── purchase_order.py        # purchase.order + purchase.order.line extensions
├── views/
│   ├── institution_views.xml    # Institution list, form, search, action
│   ├── rc_agreement_views.xml   # RC list, form, search, action
│   ├── purchase_order_views.xml # PO form (inherited), list, kanban, search
│   └── menu_views.xml           # Top-level Govt Supply menu
├── security/
│   └── ir.model.access.csv      # Access rights
├── data/
│   ├── institution_data.xml     # Pre-loaded: AP ESI, TG ESI, APSMIDC, TSMSIDC, DHS Goa, CGHS, Defence
│   ├── rc_stage_data.xml        # Placeholder
│   └── rc_agreement_data.xml    # Pre-loaded: all 12 RC rows from your Excel
└── README.md                    # This file
```
