# "Client Stack" -> "Odoo Clients 360" rebrand. Same pattern as the earlier
# "Odoo Client Hub" -> "Client Stack" rebrand (19.7.08/19.7.37): noupdate="1" records
# (the two mail templates, the renewal product) don't get their XML re-applied on a
# plain upgrade, and ir.module.module.shortdesc is only refreshed from the manifest on
# "Update Apps List", not on install/upgrade — so all of these need patching directly.
#
# Also: on a module UPGRADE (not a fresh install), Odoo's translation loader does not
# overwrite a field's already-present translation for a language, even once the
# English source and i18n/bs.po both have the new text — it only fills in translations
# that were previously empty. So every affected field's bs_BA value is set directly
# here too, not just en_US, for every language this module ships (currently just bs_BA).
#
# IMPORTANT: every write below uses an environment with an EXPLICIT lang= context —
# never an empty/ambient one. An earlier version of this script wrote the English text
# under a context-less `api.Environment(cr, SUPERUSER_ID, {})`, which on this DB (whose
# base/install language is bs_BA) ended up landing in — or later got overwritten to
# match — the bs_BA slot, corrupting the en_US value to literal Bosnian text. Confirmed
# and fixed live in 19.12.x; keeping both language writes fully explicit here so a
# fresh install running this migration doesn't reproduce it.

import logging

_logger = logging.getLogger(__name__)

_EN_US = {
    'ir.module.module,shortdesc': 'Odoo Clients 360',
    'mail.template,ts_partner_app.mail_template_asset_expiry,name': 'Odoo Clients 360: Asset Expiry Reminder',
    'mail.template,ts_partner_app.mail_template_asset_expiry_client,name':
        'Odoo Clients 360: Client Renewal Reminder',
    'product.product,ts_partner_app.product_asset_renewal,description_sale':
        'Renewal of a client asset managed via Odoo Clients 360.',
}

_BS_BA = {
    'ir.module.module,shortdesc': 'Odoo Clients 360',
    'mail.template,ts_partner_app.mail_template_asset_expiry,name': 'Odoo Clients 360: Podsjetnik za istek sredstva',
    'mail.template,ts_partner_app.mail_template_asset_expiry_client,name':
        'Odoo Clients 360: Podsjetnik za obnovu klijenta',
    'product.product,ts_partner_app.product_asset_renewal,description_sale':
        'Obnova sredstva klijenta kojim se upravlja putem Odoo Clients 360.',
    'ir.module.category,ts_partner_app.module_category_client_hub,description':
        'Nivoi pristupa za aplikaciju Odoo Clients 360.',
}


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env_en = env(context={'lang': 'en_US'})
    env_bs = env(context={'lang': 'bs_BA'})

    module = env['ir.module.module'].search([('name', '=', 'ts_partner_app')], limit=1)
    template = env.ref('ts_partner_app.mail_template_asset_expiry', raise_if_not_found=False)
    client_template = env.ref('ts_partner_app.mail_template_asset_expiry_client', raise_if_not_found=False)
    product = env.ref('ts_partner_app.product_asset_renewal', raise_if_not_found=False)
    category = env.ref('ts_partner_app.module_category_client_hub', raise_if_not_found=False)

    if module:
        env_en['ir.module.module'].browse(module.id).write(
            {'shortdesc': _EN_US['ir.module.module,shortdesc']})
    if template:
        env_en['mail.template'].browse(template.id).write(
            {'name': _EN_US['mail.template,ts_partner_app.mail_template_asset_expiry,name']})
    if client_template:
        env_en['mail.template'].browse(client_template.id).write(
            {'name': _EN_US['mail.template,ts_partner_app.mail_template_asset_expiry_client,name']})
    if product:
        env_en['product.product'].browse(product.id).write(
            {'description_sale': _EN_US['product.product,ts_partner_app.product_asset_renewal,description_sale']})

    # Direct bs_BA patch — see module docstring above for why this can't be left to
    # the normal i18n/bs.po reload.
    if module:
        env_bs['ir.module.module'].browse(module.id).write({'shortdesc': _BS_BA['ir.module.module,shortdesc']})
    if template:
        env_bs['mail.template'].browse(template.id).write(
            {'name': _BS_BA['mail.template,ts_partner_app.mail_template_asset_expiry,name']})
    if client_template:
        env_bs['mail.template'].browse(client_template.id).write(
            {'name': _BS_BA['mail.template,ts_partner_app.mail_template_asset_expiry_client,name']})
    if product:
        env_bs['product.product'].browse(product.id).write(
            {'description_sale': _BS_BA['product.product,ts_partner_app.product_asset_renewal,description_sale']})
    if category:
        env_bs['ir.module.category'].browse(category.id).write(
            {'description': _BS_BA['ir.module.category,ts_partner_app.module_category_client_hub,description']})

    _logger.info("ts_partner_app: rebranded 'Client Stack' -> 'Odoo Clients 360'.")
