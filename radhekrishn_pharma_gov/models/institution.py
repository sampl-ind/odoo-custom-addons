# -*- coding: utf-8 -*-
from odoo import models, fields, api


class RkInstitution(models.Model):
    """
    Government institutions that issue POs under rate contracts.
    Examples: AP ESI (CDS Rajamahendravaram), TG ESI, APSMIDC, TSMSIDC, DHS Goa/MSD,
              CGHS Delhi, Defence Health Services, ESIC, Railway Hospitals.
    """
    _name = 'rk.institution'
    _description = 'Government Institution'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(
        string='Institution Name',
        required=True,
        help='e.g. AP ESI, TG ESI, APSMIDC, TSMSIDC, DHS Goa MSD',
    )
    code = fields.Char(
        string='Short Code',
        help='e.g. APESI, TGESI, APSMIDC',
    )
    gst_number = fields.Char(string='GST Number')
    pan_number = fields.Char(string='PAN Number')

    institution_type = fields.Selection([
        ('esi', 'ESIC / ESI'),
        ('smidc', 'SMIDC / Medical Supply Depot'),
        ('dhs', 'DHS / Directorate of Health Services'),
        ('cghs', 'CGHS'),
        ('defence', 'Defence Health Services'),
        ('railway', 'Railway Hospital'),
        ('other', 'Other Government'),
    ], string='Institution Type', default='esi')

    state = fields.Selection([
        ('AP', 'Andhra Pradesh'),
        ('TG', 'Telangana'),
        ('GA', 'Goa'),
        ('DL', 'Delhi'),
        ('MH', 'Maharashtra'),
        ('OTHER', 'Other'),
    ], string='State', default='AP')

    nodal_officer = fields.Char(string='Nodal Officer Name')
    email = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    address = fields.Text(string='Address')

    # CDS / Supply depot reference
    cds_code = fields.Char(string='CDS Code', help='e.g. CDS 2 Rajamahendravaram')
    eaushadhi_username = fields.Char(
        string='eAushadhi Username',
        help='Login username for uploading invoices and drug analysis reports on eAushadhi portal',
    )

    # Payment behaviour
    payment_mode = fields.Selection([
        ('cheque', 'Cheque'),
        ('rtgs', 'RTGS'),
        ('neft', 'NEFT'),
        ('dd', 'Demand Draft'),
    ], string='Payment Mode', default='cheque')

    avg_payment_days = fields.Integer(
        string='Avg. Payment Days',
        help='Historical average days taken to pay after QC clearance',
    )

    # Active rate contracts count (computed)
    rc_count = fields.Integer(
        string='Active RCs',
        compute='_compute_rc_count',
    )
    po_count = fields.Integer(
        string='Total POs',
        compute='_compute_po_count',
    )
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Internal Notes')

    # ------------------------------------------------------------------ #
    # Computed                                                             #
    # ------------------------------------------------------------------ #

    def _compute_rc_count(self):
        for rec in self:
            rec.rc_count = self.env['rk.rc.agreement'].search_count([
                ('institution_ids', 'in', rec.id),
                ('status', '=', 'active'),
            ])

    def _compute_po_count(self):
        for rec in self:
            rec.po_count = self.env['purchase.order'].search_count([
                ('rk_institution_id', '=', rec.id),
            ])

    # ------------------------------------------------------------------ #
    # Smart button actions                                                 #
    # ------------------------------------------------------------------ #

    def action_view_pos(self):
        return {
            'name': 'Purchase Orders',
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('rk_institution_id', '=', self.id)],
            'context': {'default_rk_institution_id': self.id},
        }

    def action_view_rcs(self):
        return {
            'name': 'Rate Contracts',
            'type': 'ir.actions.act_window',
            'res_model': 'rk.rc.agreement',
            'view_mode': 'list,form',
            'domain': [('institution_ids', 'in', self.id)],
        }
