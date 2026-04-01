# -*- coding: utf-8 -*-
"""
Post-install hook for radhekrishn_pharma_gov.

Runs after the module installs to:
1. Create vendor partner records (USV, Tablets India, Midas Care, Ajantha) if they don't exist
2. Link each RC agreement to the correct vendor by name
3. Link each RC agreement to the correct institution(s)
4. Create generic drug product records if they don't exist

This solves the XML data limitation where Many2one vendor refs cannot be
created inline — partners must exist before RC records reference them.
"""

import logging
_logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- #
# Vendor master: name → (GST, email, city, RC item codes they cover)    #
# --------------------------------------------------------------------- #
VENDORS = {
    'USV Pvt Ltd': {
        'street': 'Windsor, 2nd Floor, C.S.T. Road, Kalina',
        'city': 'Mumbai',
        'state_name': 'Maharashtra',
        'country': 'India',
        'phone': '022-2659 2222',
        'email': 'info@usvpvtltd.com',
        'website': 'https://www.usvpvtltd.com',
        'vat': '27AABCU0457C1ZB',
        'comment': 'RC 169 vendor — Calcium OS, Calcium FD, Cough Syrup (Prospan)',
    },
    'Tablets India Ltd': {
        'street': 'SIPCOT Industrial Complex',
        'city': 'Chennai',
        'state_name': 'Tamil Nadu',
        'country': 'India',
        'email': 'export@tabletsindia.com',
        'website': 'https://www.tabletsindia.com',
        'comment': 'RC 169 vendor — Astymin M Forte, Bifilac HP, Astyfer XT, Biors Sachet, Neutrosec; RC 159 TSMSIDC',
    },
    'Midas Care Pharmaceuticals': {
        'city': 'Mumbai',
        'country': 'India',
        'comment': 'RC 169 vendor — Diclofenac Spray (Relispray) for AP ESI/TG ESI; RC 166 for APSMIDC',
    },
    'Ajantha Pharma Ltd': {
        'city': 'Mumbai',
        'country': 'India',
        'comment': 'RC 169 vendor — AntiOxidant Tab (Canate)',
    },
}

# --------------------------------------------------------------------- #
# RC agreement XML IDs → vendor name mapping                             #
# (matches xml id in rc_agreement_data.xml)                              #
# --------------------------------------------------------------------- #
RC_VENDOR_MAP = {
    'rc_169_calcium_os':          'USV Pvt Ltd',
    'rc_169_calcium_fd':          'USV Pvt Ltd',
    'rc_169_cough_syrup':         'USV Pvt Ltd',
    'rc_169_diclofenac_midas':    'Midas Care Pharmaceuticals',
    'rc_169_antioxidant_ajantha': 'Ajantha Pharma Ltd',
    'rc_169_astymin_forte':       'Tablets India Ltd',
    'rc_169_bifilac':             'Tablets India Ltd',
    'rc_169_astyfer_xt':          'Tablets India Ltd',
    'rc_169_biors':               'Tablets India Ltd',
    'rc_169_neutrosec':           'Tablets India Ltd',
    'rc_166_diclofenac_apsmidc':  'Midas Care Pharmaceuticals',
    'rc_159_astyfer_tsmsidc':     'Tablets India Ltd',
}

# --------------------------------------------------------------------- #
# RC agreement XML IDs → institution codes mapping                       #
# --------------------------------------------------------------------- #
RC_INSTITUTION_MAP = {
    'rc_169_calcium_os':          ['APESI-RJY', 'TGESI'],
    'rc_169_calcium_fd':          ['APESI-RJY', 'TGESI'],
    'rc_169_cough_syrup':         ['APESI-RJY', 'TGESI'],
    'rc_169_diclofenac_midas':    ['APESI-RJY', 'TGESI'],
    'rc_169_antioxidant_ajantha': ['APESI-RJY', 'TGESI'],
    'rc_169_astymin_forte':       ['APESI-RJY', 'TGESI'],
    'rc_169_bifilac':             ['APESI-RJY', 'TGESI'],
    'rc_169_astyfer_xt':          ['APESI-RJY', 'TGESI'],
    'rc_169_biors':               ['APESI-RJY', 'TGESI'],
    'rc_169_neutrosec':           ['APESI-RJY', 'TGESI'],
    'rc_166_diclofenac_apsmidc':  ['APSMIDC'],
    'rc_159_astyfer_tsmsidc':     ['TSMSIDC'],
}

# --------------------------------------------------------------------- #
# Product definitions                                                    #
# generic drug name → brand / notes                                      #
# --------------------------------------------------------------------- #
PRODUCTS = {
    'Calcium Supplement OS Tablet': 'Calcium + D3 OS formulation tablet',
    'Calcium Supplement FD Tablet': 'Calcium + D3 FD formulation tablet',
    'Cough Syrup 100ml (Ivy Leaf Extract)': 'Dried Ivy Leaf Extract 0.7gm / 100ml; ESI Item 1664 / RC Item 2115',
    'Diclofenac Diethylamine Topical Spray': 'Topical NSAID spray; Relispray brand',
    'AntiOxidant Tablet': 'Multivitamin antioxidant tablet; Canate brand',
    'Astymin M Forte Capsule': 'Amino acid + multivitamin capsule',
    'Bifilac HP Capsule': 'Probiotic + enzyme capsule',
    'Astyfer XT Tablet': 'Iron + folic acid + B12 tablet',
    'Biors Sachet': 'Probiotic sachet',
    'Neutrosec Liquid': 'Antacid suspension liquid',
}


def _get_or_create_vendor(env, name, vals):
    """Return existing vendor partner or create one."""
    partner = env['res.partner'].search([
        ('name', 'ilike', name),
        ('supplier_rank', '>', 0),
    ], limit=1)
    if not partner:
        partner = env['res.partner'].search([('name', 'ilike', name)], limit=1)
    if not partner:
        create_vals = {'name': name, 'supplier_rank': 1, 'company_type': 'company'}
        create_vals.update({k: v for k, v in vals.items() if k not in ('state_name', 'country')})
        # Country
        country = env['res.country'].search([('name', '=', 'India')], limit=1)
        if country:
            create_vals['country_id'] = country.id
        partner = env['res.partner'].create(create_vals)
        _logger.info('[rk] Created vendor: %s (id=%s)', name, partner.id)
    else:
        if partner.supplier_rank == 0:
            partner.supplier_rank = 1
        _logger.info('[rk] Found existing vendor: %s (id=%s)', name, partner.id)
    return partner


def _get_or_create_product(env, name, description):
    """Return existing product or create a consumable."""
    product = env['product.product'].search([('name', '=', name)], limit=1)
    if not product:
        product = env['product.product'].create({
            'name': name,
            'description': description,
            'type': 'consu',
            'purchase_ok': True,
            'sale_ok': False,
        })
        _logger.info('[rk] Created product: %s (id=%s)', name, product.id)
    return product


def post_init_hook(env):
    """
    Called by Odoo after all module XML data has been loaded.
    Links vendors and institutions to RC agreement records.
    """
    _logger.info('[rk] Running post_init_hook — linking vendors and institutions to RC agreements')

    Module = env['ir.model.data']

    # 1. Create/find vendor partners
    vendor_map = {}
    for vendor_name, vals in VENDORS.items():
        partner = _get_or_create_vendor(env, vendor_name, vals)
        vendor_map[vendor_name] = partner

    # 2. Create/find products
    product_map = {}
    for product_name, description in PRODUCTS.items():
        product = _get_or_create_product(env, product_name, description)
        product_map[product_name] = product

    # Product name → RC xml_id mapping
    PRODUCT_RC_MAP = {
        'rc_169_calcium_os':          'Calcium Supplement OS Tablet',
        'rc_169_calcium_fd':          'Calcium Supplement FD Tablet',
        'rc_169_cough_syrup':         'Cough Syrup 100ml (Ivy Leaf Extract)',
        'rc_169_diclofenac_midas':    'Diclofenac Diethylamine Topical Spray',
        'rc_166_diclofenac_apsmidc':  'Diclofenac Diethylamine Topical Spray',
        'rc_169_antioxidant_ajantha': 'AntiOxidant Tablet',
        'rc_169_astymin_forte':       'Astymin M Forte Capsule',
        'rc_169_bifilac':             'Bifilac HP Capsule',
        'rc_169_astyfer_xt':          'Astyfer XT Tablet',
        'rc_159_astyfer_tsmsidc':     'Astyfer XT Tablet',
        'rc_169_biors':               'Biors Sachet',
        'rc_169_neutrosec':           'Neutrosec Liquid',
    }

    # 3. For each RC record, set vendor_id, product_id, institution_ids
    for xml_id, vendor_name in RC_VENDOR_MAP.items():
        try:
            rc_rec = Module.sudo()._xmlid_to_res_id(
                'radhekrishn_pharma_gov.%s' % xml_id, raise_if_not_found=False
            )
            if not rc_rec:
                _logger.warning('[rk] RC record not found for xml_id: %s', xml_id)
                continue

            rc = env['rk.rc.agreement'].browse(rc_rec)
            if not rc.exists():
                continue

            # Set vendor
            vendor = vendor_map.get(vendor_name)
            if vendor:
                rc.vendor_id = vendor.id

            # Set product
            product_name = PRODUCT_RC_MAP.get(xml_id)
            if product_name and product_name in product_map:
                rc.product_id = product_map[product_name].id

            # Set institutions
            inst_codes = RC_INSTITUTION_MAP.get(xml_id, [])
            if inst_codes:
                institutions = env['rk.institution'].search([
                    ('code', 'in', inst_codes),
                ])
                if institutions:
                    rc.institution_ids = [(6, 0, institutions.ids)]

            _logger.info('[rk] Linked RC %s → vendor: %s, institutions: %s',
                         xml_id, vendor_name, inst_codes)

        except Exception as e:
            _logger.error('[rk] Error linking RC %s: %s', xml_id, str(e))

    # 4. Create a service product for commission invoicing
    commission_product = env['product.product'].search([
        ('name', '=', 'Commission Service — Govt Supply'),
    ], limit=1)
    if not commission_product:
        env['product.product'].create({
            'name': 'Commission Service — Govt Supply',
            'type': 'service',
            'invoice_policy': 'order',
            'description_sale': 'Commission on government pharma supply under rate contract',
        })
        _logger.info('[rk] Created commission service product')

    _logger.info('[rk] post_init_hook complete')
