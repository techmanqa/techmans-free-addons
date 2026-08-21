from odoo import models, fields


class PartnerAssetCredentialLog(models.Model):
    _name = 'partner.asset.credential.log'
    _description = 'Credential Access Log'
    _order = 'create_date desc'
    _log_access = True

    asset_id = fields.Many2one('partner.asset', string='Asset',
                               ondelete='cascade', index=True)
    infrastructure_id = fields.Many2one('partner.infrastructure', string='Infrastructure Profile',
                                        ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='User', required=True)
    action = fields.Selection([
        ('reveal', 'Revealed'),
        ('update', 'Updated'),
    ], string='Action', required=True)
    field_name = fields.Char(string='Field')

    _asset_or_infra_required = models.Constraint(
        'check (asset_id is not null or infrastructure_id is not null)',
        'A credential log entry must be linked to an asset or an infrastructure profile.',
    )
