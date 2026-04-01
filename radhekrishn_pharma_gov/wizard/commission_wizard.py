# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class RkCommissionSummaryWizard(models.TransientModel):
    """
    Wizard to generate the monthly commission summary PDF for a vendor.
    Filters POs by vendor, date range, and stage.
    """
    _name = 'rk.commission.summary.wizard'
    _description = 'Monthly Commission Summary Wizard'

    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=True,
        domain=[('supplier_rank', '>', 0)],
        help='Select the vendor company to generate summary for',
    )
    date_from = fields.Date(
        string='From Date',
        required=True,
        help='Start of the period (filter by PO approval date)',
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        default=fields.Date.today,
        help='End of the period (filter by PO approval date)',
    )
    include_stages = fields.Many2many(
        'ir.model.fields.selection',
        string='Include Stages',
    )
    stage_filter = fields.Selection([
        ('all', 'All stages'),
        ('active', 'Active only (exclude Closed)'),
        ('closed', 'Closed only'),
        ('pending_commission', 'Commission Pending only'),
    ], string='Stage Filter', default='all')

    po_count = fields.Integer(
        string='Matching POs',
        compute='_compute_po_count',
    )
    total_commission = fields.Float(
        string='Total Commission (₹)',
        compute='_compute_po_count',
        digits=(14, 2),
    )
    total_pending = fields.Float(
        string='Commission Pending (₹)',
        compute='_compute_po_count',
        digits=(14, 2),
    )

    @api.depends('vendor_id', 'date_from', 'date_to', 'stage_filter')
    def _compute_po_count(self):
        for wiz in self:
            pos = wiz._get_pos()
            wiz.po_count = len(pos)
            wiz.total_commission = sum(pos.mapped('rk_commission_amount'))
            wiz.total_pending = sum(pos.mapped('rk_commission_pending'))

    def _get_pos(self):
        self.ensure_one()
        domain = [
            ('rk_vendor_company_id', '=', self.vendor_id.id),
            ('rk_institution_id', '!=', False),
        ]
        if self.date_from:
            domain += [('rk_po_approval_date', '>=', self.date_from)]
        if self.date_to:
            domain += [('rk_po_approval_date', '<=', self.date_to)]
        if self.stage_filter == 'active':
            domain += [('rk_stage', '!=', 'closed')]
        elif self.stage_filter == 'closed':
            domain += [('rk_stage', '=', 'closed')]
        elif self.stage_filter == 'pending_commission':
            domain += [('rk_commission_pending', '>', 0)]
        return self.env['purchase.order'].search(domain)

    def action_generate_report(self):
        self.ensure_one()
        pos = self._get_pos()
        if not pos:
            raise UserError(
                'No Purchase Orders found for %s in the selected period / filter.' % self.vendor_id.name
            )
        # Report model is purchase.order — pass PO records directly as docs
        return self.env.ref(
            'radhekrishn_pharma_gov.action_report_rk_commission_summary'
        ).report_action(pos)

    def action_view_pos(self):
        """Jump to list of matching POs without closing wizard."""
        pos = self._get_pos()
        return {
            'name': 'Matching POs — %s' % self.vendor_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pos.ids)],
        }


class RkBulkPaymentWizard(models.TransientModel):
    """
    Wizard to record a single institution payment (cheque/RTGS) that
    covers multiple POs in one go. Useful when institution pays all
    outstanding bills in one cheque.
   """
    _name = 'rk.bulk.payment.wizard'
    _description = 'Record Bulk Institution Payment'

    institution_id = fields.Many2one(
        'rk.institution',
        string='Institution',
        required=True,
    )
    payment_date = fields.Date(
        string='Payment Date',
        required=True,
        default=fields.Date.today,
    )
    cheque_rtgs_number = fields.Char(
        string='Cheque / RTGS / NEFT Number',
        required=True,
    )
    payment_instrument_date = fields.Date(
        string='Cheque / Instrument Date',
    )
    total_amount = fields.Float(
        string='Total Amount Received (₹)',
        required=True,
        digits=(14, 2),
    )
    tds_deducted = fields.Float(
        string='TDK Deducted (₹)',
        digits=(14, 2),
        default=0.0,
    )
    security_deposit = fields.Float(
        string='Security Deposit (₹)',
        digits=(14, 2),
        default=0.0,
    )
    penalty_deducted = fields.Float(
        string='Penalty Deducted (₹)',
        digits=(14, 2),
        default=0.0,
    )
    notes = fields.Text(string='Notes / Deduction Details')

    # POs to apply this payment to
    po_ids = fields.Many2many(
        'purchase.order',
        string='Purchase Orders',
        domain="[('rk_institution_id', '=', institution_id), ('rk_stage', '=', 'qc_cleared')]",
        help='Select the QC-cleared POs covered by this payment',
    )

    net_received = fields.Float(
        string='Net Received (₹)',
        compute='_compute_net',
        digits=(14, 2),
    )
    po_total = fields.Float(
        string='Total PO Value (₹)',
        compute='_compute_po_total',
        digits=(14, 2),
    )


    @api.depends('total_amount', 'tds_deducted', 'security_deposit', 'penalty_deducted')
    def _compute_net(self):
        for wiz in self:
            wiz.net_received = (
                wiz.total_amount - wiz.tds_deducted
                - wiz.security_deposit - wiz.penalty_deducted
            )

    @api.depends('po_ids')
    def _compute_po_total(self):
        for wiz in self:
            wiz.po_total = sum(wiz.po_ids.mapped('amount_total'))

    def action_apply_payment(self):
        """
        Apply the payment details to all selected POs and advance their stage.
        Proportionally distributes deductions across POs by PO value.
       """
        self.ensure_one()
        if not self.po_ids:
            raise UserError('Please select at least one Purchase Order.')

        total_po_val = sum(self.po_ids.mapped('amount_total')) or 1.0

        for po in self.po_ids:
            ratio = po.amount_total / total_po_val
            po.write({
                'rk_inst_payment_date': self.payment_date,
                'rk_cheque_rtgs_number': self.cheque_rtgs_number,
                'rk_payment_instrument_date': self.payment_instrument_date or self.payment_date,
                'rk_gross_amount_received': po.amount_total,
                'rk_tds_deducted': round(self.tds_deducted * ratio, 2),
                'rk_security_deposit_deducted': round(self.security_deposit * ratio, 2),
                'rk_penalty_deducted_by_inst': round(self.penalty_deducted * ratio, 2),
                'rk_deduction_notes': self.notes or '',
                'rk_stage': 'inst_paid',
            })
            po.message_post(
                body='Payment recorded via Bulk Payment Wizard. '
                      'Cheque/RTGS: %s dated %s. '
                      'Gross: ₹%.2f, Net: ₹%.2f' % (
                           self.cheque_rtgs_number,
                           self.payment_date,
                            po.amount_total,
                            po.amount_total - round(
                                (self.tds_deducted + self.security_deposit + self.penalty_deducted) * ratio, 2
                          ),
                      ),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

        return {
            'name': 'Updated POs',
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_wode': 'list,form',
            'domain': [('id', 'in', self.po_ids.ids)],
        }
