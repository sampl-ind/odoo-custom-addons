# -*- coding: utf-8 -*-
import math
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class PurchaseOrder(models.Model):
    """
    Extends standard Odoo purchase.order with:
    - 6-stage Kanban pipeline (Received → Forwarded → Dispatched → QC Cleared → Paid → Closed)
    - Institution, RC, and vendor company linkage
    - Dispatch details (LR number, batch, expiry)
    - QC clearance tracking
    - Payment received from institution with full deduction breakdown
    - Commission calculation and invoice generation to vendor
    - Supply penalty auto-calculation
    - Claim interest auto-calculation
    """
    _inherit = 'purchase.order'

    # ------------------------------------------------------------------ #
    # Stage / Pipeline                                                     #
    # ------------------------------------------------------------------ #

    rk_stage = fields.Selection([
        ('po_received',   '1. PO Received'),
        ('forwarded',     '2. Forwarded to Vendor'),
        ('dispatched',    '3. Dispatched'),
        ('qc_cleared',    '4. QC Cleared'),
        ('inst_paid',     '5. Institution Paid'),
        ('closed',        '6. Closed'),
    ], string='Stage', default='po_received', tracking=True,
       help='6-stage lifecycle for each government PO')

    rk_priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'Urgent'),
        ('2', 'Emergency'),
    ], string='Priority', default='0')

    # ------------------------------------------------------------------ #
    # PO Identity                                                          #
    # ------------------------------------------------------------------ #

    rk_po_prefix = fields.Char(
        string='PO Prefix / Series',
        help='e.g. PO/2025-2026/3032',
    )
    rk_po_number = fields.Char(
        string='Institution PO Number',
        help='Full PO number as printed on the institution PO, e.g. 10282600172',
    )
    rk_po_approval_date = fields.Date(
        string='PO Approval Date',
        help='Date the institution approved / generated the PO',
    )

    # ------------------------------------------------------------------ #
    # Linkages                                                             #
    # ------------------------------------------------------------------ #

    rk_institution_id = fields.Many2one(
        'rk.institution',
        string='Institution',
        required=True,
        tracking=True,
        help='Government institution that issued this PO (e.g. AP ESI CDS 2 Rajamahendravaram)',
    )
    rk_vendor_company_id = fields.Many2one(
        'res.partner',
        string='Vendor Company',
        domain=[('supplier_rank', '>', 0)],
        tracking=True,
        help='Pharma company to which this PO is forwarded (e.g. USV Pvt Ltd)',
    )
    rk_rc_agreement_id = fields.Many2one(
        'rk.rc.agreement',
        string='Rate Contract',
        help='RC agreement governing pricing and penalties for this PO',
    )
    rk_rc_number = fields.Char(
        string='RC Number',
        related='rk_rc_agreement_id.rc_number',
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------------ #
    # Supply timeline                                                      #
    # ------------------------------------------------------------------ #

    rk_po_receipt_date = fields.Date(
        string='PO Received Date',
        default=fields.Date.today,
        help='Date Radhekrishn Biotech received the PO from institution',
    )
    rk_forwarded_date = fields.Date(
        string='Forwarded to Vendor Date',
        tracking=True,
    )
    rk_vendor_acceptance_date = fields.Date(
        string='Vendor Acceptance Date',
        help='Date vendor confirmed acceptance of this PO (clock starts here for supply deadline)',
    )
    rk_supply_due_date = fields.Date(
        string='Supply Due Date',
        compute='_compute_supply_due_date',
        store=True,
        readonly=False,
        help='Auto-calculated: vendor acceptance date + normal supply days (default 42 days per ESI terms)',
    )
    rk_supply_extended_due_date = fields.Date(
        string='Extended Due Date',
        compute='_compute_supply_due_date',
        store=True,
        readonly=False,
        help='Maximum date after extension (acceptance + 77 days for ESI)',
    )
    rk_supply_days = fields.Integer(
        string='Normal Supply Days',
        default=42,
        help='Days allowed for supply from vendor acceptance. ESI standard = 42 days.',
    )
    rk_extension_days = fields.Integer(
        string='Max Extension Days',
        default=35,
    )

    # ------------------------------------------------------------------ #
    # Dispatch details (Step 2)                                            #
    # ------------------------------------------------------------------ #

    rk_dispatch_date = fields.Date(string='Dispatch Date', tracking=True)
    rk_lr_number = fields.Char(string='LR / GR Number', help='Lorry Receipt or Goods Receipt number')
    rk_transporter = fields.Char(string='Transporter Name')
    rk_batch_number = fields.Char(string='Batch Number')
    rk_mfg_date = fields.Date(string='Manufacturing Date')
    rk_expiry_date = fields.Date(string='Expiry Date')
    rk_qty_dispatched = fields.Float(string='Qty Dispatched', digits=(10, 3))
    rk_dispatch_notes = fields.Text(string='Dispatch Notes')

    # Delay computation
    rk_delay_days = fields.Integer(
        string='Supply Delay (days)',
        compute='_compute_delay',
        store=True,
        help='Days of delay beyond supply due date. Negative = early supply.',
    )
    rk_delay_weeks = fields.Integer(
        string='Delay Weeks (for penalty)',
        compute='_compute_delay',
        store=True,
    )

    # ------------------------------------------------------------------ #
    # QC Clearance (Step 3)                                                #
    # ------------------------------------------------------------------ #

    rk_qc_status = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('partial', 'Partial Approval'),
    ], string='QC Status', default='pending', tracking=True)

    rk_qc_date = fields.Date(string='QC Clearance Date', tracking=True)
    rk_qty_accepted = fields.Float(string='Qty Accepted', digits=(10, 3))
    rk_qc_report_ref = fields.Char(
        string='QC Report Batch Ref',
        help='Batch number referenced in QC/drug analysis report uploaded on eAushadhi',
    )

    # ------------------------------------------------------------------ #
    # Supply penalty (auto-calculated)                                     #
    # ------------------------------------------------------------------ #

    rk_supply_penalty_amount = fields.Float(
        string='Supply Penalty Amount (₹)',
        compute='_compute_supply_penalty',
        store=True,
        digits=(10, 2),
        help='2% per week of delay on PO value, capped at 10%. Auto-calculated from dispatch vs due date.',
    )
    rk_supply_penalty_pct = fields.Float(
        string='Penalty %',
        compute='_compute_supply_penalty',
        store=True,
        digits=(5, 2),
    )

    # ------------------------------------------------------------------ #
    # Claim / Payment from Institution (Step 4)                            #
    # ------------------------------------------------------------------ #

    rk_bill_submitted_date = fields.Date(string='Bill Submitted to Institution Date')
    rk_inst_payment_date = fields.Date(string='Institution Payment Date', tracking=True)
    rk_cheque_rtgs_number = fields.Char(string='Cheque / RTGS / NEFT Number')
    rk_payment_instrument_date = fields.Date(string='Cheque / Instrument Date')

    rk_gross_amount_received = fields.Float(
        string='Gross Amount Received from Inst. (₹)',
        digits=(14, 2),
    )
    rk_tds_deducted = fields.Float(
        string='TDS Deducted (₹)',
        digits=(14, 2),
        default=0.0,
    )
    rk_security_deposit_deducted = fields.Float(
        string='Security Deposit Deducted (₹)',
        digits=(14, 2),
        default=0.0,
    )
    rk_penalty_deducted_by_inst = fields.Float(
        string='Penalty Deducted by Institution (₹)',
        digits=(14, 2),
        default=0.0,
        help='Actual supply penalty amount deducted by institution from payment',
    )
    rk_other_deductions = fields.Float(
        string='Other Deductions (₹)',
        digits=(14, 2),
        default=0.0,
    )
    rk_net_received_from_inst = fields.Float(
        string='Net Received from Institution (₹)',
        compute='_compute_net_received',
        store=True,
        digits=(14, 2),
    )
    rk_deduction_notes = fields.Text(string='Deduction Details / Notes')

    # Claim interest (late payment by institution)
    rk_claim_days_elapsed = fields.Integer(
        string='Days Since QC (for claim)',
        compute='_compute_claim_interest',
        store=True,
    )
    rk_claim_overdue_weeks = fields.Integer(
        string='Overdue Weeks',
        compute='_compute_claim_interest',
        store=True,
    )
    rk_claim_interest_amount = fields.Float(
        string='Claim Interest Accrued (₹)',
        compute='_compute_claim_interest',
        store=True,
        digits=(14, 2),
        help='Interest on delayed payment by institution at 0.5%/week after free period',
    )

    # ------------------------------------------------------------------ #
    # Commission / Proforma Invoice to Vendor (Step 5)                     #
    # ------------------------------------------------------------------ #

    rk_commission_percent = fields.Float(
        string='Commission %',
        compute='_compute_commission',
        store=True,
        readonly=False,
        digits=(5, 2),
        help='Auto-pulled from Rate Contract. Can be overridden.',
    )
    rk_commission_base = fields.Float(
        string='Commission Base Amount (₹)',
        compute='_compute_commission',
        store=True,
        digits=(14, 2),
        help='Gross amount received from institution (pre-deductions) used as commission base',
    )
    rk_commission_amount = fields.Float(
        string='Commission Amount (₹)',
        compute='_compute_commission',
        store=True,
        digits=(14, 2),
    )
    rk_proforma_invoice_number = fields.Char(string='Proforma Invoice Number')
    rk_proforma_invoice_date = fields.Date(string='Proforma Invoice Date')
    rk_sale_order_id = fields.Many2one(
        'sale.order',
        string='Commission Sale Order',
        readonly=True,
        help='Odoo sale order generated for commission invoice to vendor',
    )

    # Amount to remit to vendor after deducting commission
    rk_amount_remit_to_vendor = fields.Float(
        string='Amount to Remit to Vendor (₹)',
        compute='_compute_commission',
        store=True,
        digits=(14, 2),
    )

    # ------------------------------------------------------------------ #
    # Commission received from vendor (Step 6)                            #
    # ------------------------------------------------------------------ #

    rk_commission_received_date = fields.Date(
        string='Commission Received Date', tracking=True,
    )
    rk_commission_received_amount = fields.Float(
        string='Commission Received (₹)',
        digits=(14, 2),
    )
    rk_commission_bank_ref = fields.Char(string='Bank Reference / UTR')
    rk_commission_pending = fields.Float(
        string='Commission Pending (₹)',
        compute='_compute_commission_pending',
        store=True,
        digits=(14, 2),
    )

    # ------------------------------------------------------------------ #
    # Summary flags                                                        #
    # ------------------------------------------------------------------ #

    rk_is_overdue_supply = fields.Boolean(
        string='Supply Overdue?',
        compute='_compute_delay',
        store=True,
    )
    rk_is_claim_overdue = fields.Boolean(
        string='Claim Overdue?',
        compute='_compute_claim_interest',
        store=True,
    )

    # ------------------------------------------------------------------ #
    # Computed: supply due date                                            #
    # ------------------------------------------------------------------ #

    @api.depends('rk_vendor_acceptance_date', 'rk_supply_days', 'rk_extension_days')
    def _compute_supply_due_date(self):
        for po in self:
            if po.rk_vendor_acceptance_date:
                po.rk_supply_due_date = (
                    po.rk_vendor_acceptance_date + timedelta(days=po.rk_supply_days)
                )
                po.rk_supply_extended_due_date = (
                    po.rk_vendor_acceptance_date
                    + timedelta(days=po.rk_supply_days + po.rk_extension_days)
                )
            else:
                po.rk_supply_due_date = False
                po.rk_supply_extended_due_date = False

    # ------------------------------------------------------------------ #
    # Computed: delay                                                       #
    # ------------------------------------------------------------------ #

    @api.depends('rk_dispatch_date', 'rk_supply_due_date', 'rk_qc_date')
    def _compute_delay(self):
        today = fields.Date.today()
        for po in self:
            # Use QC date if available (stock physically received), else dispatch date
            delivery_date = po.rk_qc_date or po.rk_dispatch_date
            due = po.rk_supply_due_date

            if due and delivery_date:
                delay = (delivery_date - due).days
            elif due and not delivery_date:
                # Not yet delivered — calculate against today
                delay = (today - due).days
            else:
                delay = 0

            po.rk_delay_days = delay
            po.rk_delay_weeks = math.ceil(max(0, delay) / 7.0) if delay > 0 else 0
            po.rk_is_overdue_supply = delay > 0

    # ------------------------------------------------------------------ #
    # Computed: supply penalty                                             #
    # ------------------------------------------------------------------ #

    @api.depends('rk_delay_weeks', 'amount_total', 'rk_rc_agreement_id')
    def _compute_supply_penalty(self):
        for po in self:
            if po.rk_delay_weeks <= 0:
                po.rk_supply_penalty_amount = 0.0
                po.rk_supply_penalty_pct = 0.0
                continue

            # Get penalty rate from RC agreement or use ESI default (2%/week, max 10%)
            if po.rk_rc_agreement_id:
                rate = po.rk_rc_agreement_id.supply_penalty_percent_per_week / 100.0
                cap_pct = po.rk_rc_agreement_id.supply_penalty_max_percent / 100.0
            else:
                rate = 0.02  # 2% per week
                cap_pct = 0.10  # 10% max

            base = po.amount_total
            raw = base * rate * po.rk_delay_weeks
            cap = base * cap_pct
            penalty = min(raw, cap)

            po.rk_supply_penalty_amount = penalty
            po.rk_supply_penalty_pct = (penalty / base * 100.0) if base else 0.0

    # ------------------------------------------------------------------ #
    # Computed: net received from institution                              #
    # ------------------------------------------------------------------ #

    @api.depends(
        'rk_gross_amount_received',
        'rk_tds_deducted',
        'rk_security_deposit_deducted',
        'rk_penalty_deducted_by_inst',
        'rk_other_deductions',
    )
    def _compute_net_received(self):
        for po in self:
            po.rk_net_received_from_inst = (
                po.rk_gross_amount_received
                - po.rk_tds_deducted
                - po.rk_security_deposit_deducted
                - po.rk_penalty_deducted_by_inst
                - po.rk_other_deductions
            )

    # ------------------------------------------------------------------ #
    # Computed: claim interest (late payment by institution)               #
    # ------------------------------------------------------------------ #

    @api.depends(
        'rk_qc_date',
        'rk_inst_payment_date',
        'rk_gross_amount_received',
        'rk_rc_agreement_id',
        'rk_qc_status',
    )
    def _compute_claim_interest(self):
        today = fields.Date.today()
        for po in self:
            if not po.rk_qc_date or po.rk_qc_status not in ('approved', 'partial'):
                po.rk_claim_days_elapsed = 0
                po.rk_claim_overdue_weeks = 0
                po.rk_claim_interest_amount = 0.0
                po.rk_is_claim_overdue = False
                continue

            # Days elapsed from QC clearance to payment (or today if not yet paid)
            ref_date = po.rk_inst_payment_date or today
            elapsed = (ref_date - po.rk_qc_date).days
            po.rk_claim_days_elapsed = elapsed

            # Get free period and rate from RC or use defaults
            if po.rk_rc_agreement_id:
                free_days = po.rk_rc_agreement_id.claim_free_days
                weekly_rate = po.rk_rc_agreement_id.claim_penalty_percent_per_week / 100.0
            else:
                free_days = 90
                weekly_rate = 0.005  # 0.5% per week

            overdue_days = max(0, elapsed - free_days)
            overdue_weeks = math.ceil(overdue_days / 7.0) if overdue_days > 0 else 0
            po.rk_claim_overdue_weeks = overdue_weeks
            po.rk_is_claim_overdue = overdue_weeks > 0

            base = po.rk_gross_amount_received or po.amount_total
            po.rk_claim_interest_amount = base * weekly_rate * overdue_weeks

    # ------------------------------------------------------------------ #
    # Computed: commission                                                 #
    # ------------------------------------------------------------------ #

    @api.depends(
        'rk_rc_agreement_id',
        'rk_gross_amount_received',
        'amount_total',
        'rk_commission_percent',
    )
    def _compute_commission(self):
        for po in self:
            # Pull commission % from RC agreement if not manually overridden
            if po.rk_rc_agreement_id and not po._origin.rk_commission_percent:
                pct = po.rk_rc_agreement_id.margin_percent
            else:
                pct = po.rk_commission_percent or 0.0

            po.rk_commission_percent = pct
            base = po.rk_gross_amount_received or po.amount_total or 0.0
            commission = base * (pct / 100.0)
            po.rk_commission_base = base
            po.rk_commission_amount = commission
            po.rk_amount_remit_to_vendor = base - commission

    # ------------------------------------------------------------------ #
    # Computed: commission pending                                         #
    # ------------------------------------------------------------------ #

    @api.depends('rk_commission_amount', 'rk_commission_received_amount')
    def _compute_commission_pending(self):
        for po in self:
            po.rk_commission_pending = (
                po.rk_commission_amount - (po.rk_commission_received_amount or 0.0)
            )

    # ------------------------------------------------------------------ #
    # onchange: auto-fill from RC                                          #
    # ------------------------------------------------------------------ #

    @api.onchange('rk_rc_agreement_id')
    def _onchange_rc_agreement(self):
        if self.rk_rc_agreement_id:
            rc = self.rk_rc_agreement_id
            self.rk_vendor_company_id = rc.vendor_id
            self.rk_supply_days = rc.supply_days_normal
            self.rk_extension_days = rc.supply_days_extension

    @api.onchange('rk_po_approval_date')
    def _onchange_po_approval_date(self):
        """
        ESI terms: vendor must indicate acceptance within 7 days.
        Pre-fill vendor acceptance date as PO date + 7 days.
        """
        if self.rk_po_approval_date and not self.rk_vendor_acceptance_date:
            self.rk_vendor_acceptance_date = (
                self.rk_po_approval_date + timedelta(days=7)
            )

    # ------------------------------------------------------------------ #
    # Stage advancement helpers                                            #
    # ------------------------------------------------------------------ #

    def action_stage_forwarded(self):
        for po in self:
            po.rk_stage = 'forwarded'
            if not po.rk_forwarded_date:
                po.rk_forwarded_date = fields.Date.today()

    def action_stage_dispatched(self):
        for po in self:
            if not po.rk_dispatch_date:
                raise UserError(
                    'Please fill Dispatch Date and LR Number before marking as Dispatched.'
                )
            po.rk_stage = 'dispatched'

    def action_stage_qc_cleared(self):
        for po in self:
            if po.rk_qc_status not in ('approved', 'partial'):
                raise UserError(
                    'Please set QC Status to Approved or Partial before marking QC Cleared.'
                )
            if not po.rk_qc_date:
                po.rk_qc_date = fields.Date.today()
            po.rk_stage = 'qc_cleared'

    def action_stage_institution_paid(self):
        for po in self:
            if not po.rk_gross_amount_received:
                raise UserError(
                    'Please record the payment details (gross amount, cheque/RTGS number) first.'
                )
            po.rk_stage = 'inst_paid'
            if not po.rk_inst_payment_date:
                po.rk_inst_payment_date = fields.Date.today()

    def action_stage_closed(self):
        for po in self:
            po.rk_stage = 'closed'

    # ------------------------------------------------------------------ #
    # Email send actions                                                   #
    # ------------------------------------------------------------------ #

    def _get_email_compose_ctx(self, template_xmlid):
        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        return {
            'name': 'Send Email',
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(False, 'form')],
            'view_id': False,
            'target': 'new',
            'context': {
                'default_model': 'purchase.order',
                'default_res_ids': self.ids,
                'default_use_template': bool(template),
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'force_email': True,
            },
        }

    def action_send_po_to_vendor(self):
        return self._get_email_compose_ctx(
            'radhekrishn_pharma_gov.email_template_po_to_vendor'
        )

    def action_send_overdue_alert(self):
        return self._get_email_compose_ctx(
            'radhekrishn_pharma_gov.email_template_supply_overdue'
        )

    def action_send_claim_interest_notice(self):
        return self._get_email_compose_ctx(
            'radhekrishn_pharma_gov.email_template_claim_interest'
        )

    # ------------------------------------------------------------------ #
    # Generate commission sale order to vendor                             #
    # ------------------------------------------------------------------ #

    def action_create_commission_invoice(self):
        """
        Creates a Sale Order in Odoo to invoice the vendor for commission.
        The SO is addressed to the vendor company and contains one line
        for the commission amount.
        """
        self.ensure_one()
        if self.rk_sale_order_id:
            raise UserError('A commission sale order already exists for this PO: %s' % self.rk_sale_order_id.name)
        if not self.rk_vendor_company_id:
            raise UserError('Please set Vendor Company before generating commission invoice.')
        if not self.rk_commission_amount:
            raise UserError('Commission amount is zero. Please verify RC and payment details.')

        # Find or create a 'Commission Service' product
        commission_product = self.env['product.product'].search([
            ('name', 'ilike', 'Commission Service'),
            ('type', '=', 'service'),
        ], limit=1)
        if not commission_product:
            commission_product = self.env['product.product'].create({
                'name': 'Commission Service — Govt Supply',
                'type': 'service',
                'invoice_policy': 'order',
            })

        so_vals = {
            'partner_id': self.rk_vendor_company_id.id,
            'note': (
                'Commission on PO %s | Institution: %s | RC: %s\n'
                'Gross received: ₹%.2f | Commission @%.2f%%'
            ) % (
                self.rk_po_number or self.name,
                self.rk_institution_id.name if self.rk_institution_id else '',
                self.rk_rc_number or '',
                self.rk_commission_base,
                self.rk_commission_percent,
            ),
            'order_line': [(0, 0, {
                'product_id': commission_product.id,
                'name': (
                    'Commission — %s | PO %s | %s'
                ) % (
                    self.rk_rc_agreement_id.display_name if self.rk_rc_agreement_id else '',
                    self.rk_po_number or self.name,
                    self.rk_institution_id.name if self.rk_institution_id else '',
                ),
                'product_uom_qty': 1,
                'price_unit': self.rk_commission_amount,
            })],
        }
        so = self.env['sale.order'].create(so_vals)
        self.rk_sale_order_id = so.id
        self.rk_proforma_invoice_date = fields.Date.today()

        return {
            'name': 'Commission Invoice',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': so.id,
            'view_mode': 'form',
        }


class PurchaseOrderLine(models.Model):
    """
    Extend PO lines to store RC item-level details.
    """
    _inherit = 'purchase.order.line'

    rk_item_code = fields.Char(
        string='RC Item Code',
        help='Item code as listed in the Rate Contract (e.g. 1795, 2115)',
    )
    rk_brand_name = fields.Char(
        string='Brand Name',
        help='Brand name of the supplied drug',
    )
    rk_rc_agreement_line_id = fields.Many2one(
        'rk.rc.agreement',
        string='RC Line Reference',
        help='Rate contract line this PO line is based on',
    )
    rk_line_commission_amount = fields.Float(
        string='Line Commission (₹)',
        compute='_compute_line_commission',
        store=True,
        digits=(14, 2),
    )

    @api.depends('price_subtotal', 'rk_rc_agreement_line_id')
    def _compute_line_commission(self):
        for line in self:
            if line.rk_rc_agreement_line_id:
                pct = line.rk_rc_agreement_line_id.margin_percent / 100.0
                line.rk_line_commission_amount = line.price_subtotal * pct
            else:
                line.rk_line_commission_amount = 0.0
