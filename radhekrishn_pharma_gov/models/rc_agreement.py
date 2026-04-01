# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class RkRcAgreement(models.Model):
    """
    Rate Contract (RC) Master Register.
    One record = one product x vendor x institution combination under a specific RC number.
    This is the source of truth for pricing and commission when creating POs.

    Example rows from your claim sheet:
        RC 169 | USV Pvt Ltd | Cough Syrup | AP ESI + TG ESI | Rate ₹75 | Margin 22%
        RC 166 | Midas Care | Diclofenac Spray | APSMIDC | Rate ₹30 | Margin 10%
        RC 159 | Tablets India | Astyfer XT | TSMSIDC | Rate ₹7.6 | Margin 10%
    """
    _name = 'rk.rc.agreement'
    _description = 'Rate Contract Agreement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'rc_number, vendor_id, product_id'
    _rec_name = 'display_name'

    # ------------------------------------------------------------------ #
    # Identity                                                             #
    # ------------------------------------------------------------------ #

    rc_number = fields.Char(
        string='RC Number',
        required=True,
        help='Rate Contract reference number issued by institution (e.g. 166, 169, 159)',
    )
    item_code = fields.Char(
        string='Item Code',
        help='Institution-assigned item code in the rate contract',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product (Generic)',
        required=True,
        help='Generic drug name as per RC — e.g. Cough Syrup 100ml',
    )
    brand_name = fields.Char(
        string='Brand Name',
        help='Brand name as supplied — e.g. Prospan Syrup, Relispray',
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )

    # ------------------------------------------------------------------ #
    # Parties                                                              #
    # ------------------------------------------------------------------ #

    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor Company',
        required=True,
        domain=[('supplier_rank', '>', 0)],
        help='Pharma company holding the RC (e.g. USV Pvt Ltd, Tablets India)',
    )
    institution_ids = fields.Many2many(
        'rk.institution',
        'rc_agreement_institution_rel',
        'rc_id',
        'institution_id',
        string='Applicable Institutions',
        help='Institutions where this RC rate is valid (e.g. AP ESI, TG ESI)',
    )

    # ------------------------------------------------------------------ #
    # Pricing & margin                                                     #
    # ------------------------------------------------------------------ #

    rate_per_unit = fields.Float(
        string='RC Rate / Unit (₹)',
        required=True,
        digits=(10, 4),
        help='Rate as per rate contract — this is the price institution pays per unit',
    )
    margin_percent = fields.Float(
        string='Commission / Margin %',
        required=True,
        help='Radhekrishn Biotech commission percentage on each transaction',
    )
    commission_per_unit = fields.Float(
        string='Commission per Unit (₹)',
        compute='_compute_commission_per_unit',
        store=True,
        digits=(10, 4),
    )
    gst_percent = fields.Float(
        string='GST %',
        default=5.0,
        help='GST rate applicable on this product (typically 5% for pharma)',
    )

    # ------------------------------------------------------------------ #
    # Claim / payment terms                                                #
    # ------------------------------------------------------------------ #

    claim_free_days = fields.Integer(
        string='Claim Free Period (days)',
        default=90,
        help='Days after QC clearance within which institution must pay — no interest charged. Typically 90 or 120 days.',
    )
    claim_penalty_percent_per_week = fields.Float(
        string='Claim Interest %/week',
        default=0.5,
        help='Weekly interest % charged on outstanding amount after claim free period. Typically 0.5% per week.',
    )
    claim_terms_note = fields.Char(
        string='Claim Terms (text)',
        compute='_compute_claim_terms_note',
        store=True,
    )

    # ------------------------------------------------------------------ #
    # Supply / penalty terms                                               #
    # ------------------------------------------------------------------ #

    supply_days_normal = fields.Integer(
        string='Normal Supply Period (days)',
        default=42,
        help='Days from PO acceptance to complete supply. ESI standard = 42 days (6 weeks).',
    )
    supply_days_extension = fields.Integer(
        string='Max Extension Period (days)',
        default=35,
        help='Maximum extension allowed on prior approval. ESI = 35 days (5 weeks). Penalty applies during extension.',
    )
    supply_penalty_percent_per_week = fields.Float(
        string='Supply Penalty %/week',
        default=2.0,
        help='Penalty on PO value per week of delay after normal supply period. ESI = 2% per week.',
    )
    supply_penalty_max_percent = fields.Float(
        string='Max Supply Penalty %',
        default=10.0,
        help='Maximum penalty cap as % of PO value. ESI = 10%.',
    )

    # ------------------------------------------------------------------ #
    # Validity                                                             #
    # ------------------------------------------------------------------ #

    rc_validity_date = fields.Date(
        string='RC Valid Till',
        help='Date until which the rate contract is valid with the institution',
    )
    agreement_validity_date = fields.Date(
        string='Agreement Valid Till',
        help='Date until which Radhekrishn Biotech agreement with vendor is valid',
    )
    status = fields.Selection([
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('suspended', 'Suspended'),
    ], string='Status', default='active', compute='_compute_status', store=True)

    notes = fields.Text(string='Internal Notes')
    po_ids = fields.One2many(
        'purchase.order',
        'rk_rc_agreement_id',
        string='Purchase Orders',
    )
    po_count = fields.Integer(
        string='PO Count',
        compute='_compute_po_count',
    )

    # ------------------------------------------------------------------ #
    # Computed fields                                                      #
    # ------------------------------------------------------------------ #

    @api.depends('rc_number', 'product_id', 'vendor_id')
    def _compute_display_name(self):
        for rec in self:
            parts = []
            if rec.rc_number:
                parts.append('RC %s' % rec.rc_number)
            if rec.product_id:
                parts.append(rec.product_id.name)
            if rec.vendor_id:
                parts.append(rec.vendor_id.name)
            rec.display_name = ' | '.join(parts) if parts else 'New RC'

    @api.depends('rate_per_unit', 'margin_percent')
    def _compute_commission_per_unit(self):
        for rec in self:
            rec.commission_per_unit = rec.rate_per_unit * (rec.margin_percent / 100.0)

    @api.depends('claim_free_days', 'claim_penalty_percent_per_week')
    def _compute_claim_terms_note(self):
        for rec in self:
            if rec.claim_free_days and rec.claim_penalty_percent_per_week:
                rec.claim_terms_note = (
                    'After %d days every week %.1f percent'
                    % (rec.claim_free_days, rec.claim_penalty_percent_per_week)
                )
            else:
                rec.claim_terms_note = ''

    @api.depends('rc_validity_date', 'agreement_validity_date')
    def _compute_status(self):
        today = fields.Date.today()
        for rec in self:
            if rec.rc_validity_date and rec.rc_validity_date < today:
                rec.status = 'expired'
            elif rec.agreement_validity_date and rec.agreement_validity_date < today:
                rec.status = 'expired'
            else:
                rec.status = 'active'

    def _compute_po_count(self):
        for rec in self:
            rec.po_count = len(rec.po_ids)

    # ------------------------------------------------------------------ #
    # Constraints                                                          #
    # ------------------------------------------------------------------ #

    @api.constrains('margin_percent')
    def _check_margin(self):
        for rec in self:
            if rec.margin_percent < 0 or rec.margin_percent > 100:
                raise ValidationError('Margin % must be between 0 and 100.')

    @api.constrains('rate_per_unit')
    def _check_rate(self):
        for rec in self:
            if rec.rate_per_unit <= 0:
                raise ValidationError('Rate per unit must be greater than zero.')

    # ------------------------------------------------------------------ #
    # Smart button                                                         #
    # ------------------------------------------------------------------ #

    def action_view_pos(self):
        return {
            'name': 'Purchase Orders',
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('rk_rc_agreement_id', '=', self.id)],
            'context': {'default_rk_rc_agreement_id': self.id},
        }

    # ------------------------------------------------------------------ #
    # Helper: calculate claim interest                                     #
    # ------------------------------------------------------------------ #

    def calculate_claim_interest(self, bill_amount, days_elapsed):
        """
        Returns claim interest amount for a given bill and days elapsed since QC.
        Usage: rc.calculate_claim_interest(750000, 120) → float
        """
        self.ensure_one()
        overdue_days = max(0, days_elapsed - self.claim_free_days)
        if overdue_days <= 0:
            return 0.0
        import math
        overdue_weeks = math.ceil(overdue_days / 7.0)
        return bill_amount * (self.claim_penalty_percent_per_week / 100.0) * overdue_weeks

    def calculate_supply_penalty(self, po_value, delay_weeks):
        """
        Returns supply penalty amount for a given PO value and weeks of delay.
        Usage: rc.calculate_supply_penalty(750000, 2) → float
        """
        self.ensure_one()
        if delay_weeks <= 0:
            return 0.0
        raw = po_value * (self.supply_penalty_percent_per_week / 100.0) * delay_weeks
        cap = po_value * (self.supply_penalty_max_percent / 100.0)
        return min(raw, cap)
