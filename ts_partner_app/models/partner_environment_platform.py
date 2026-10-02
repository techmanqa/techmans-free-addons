from odoo import models, fields


class PartnerEnvironmentPlatform(models.Model):
    """Configurable list of the ways a client's Odoo can be hosted / packaged
    (Odoo.sh, OEC.sh, Docker, ...). The ``kind`` drives which fields the
    environment form shows; the label is free to edit / extend from
    Configuration.
    """
    _name = 'partner.environment.platform'
    _description = 'Environment Platform'
    _order = 'sequence, name'

    name = fields.Char(string='Platform', required=True, translate=True)
    kind = fields.Selection([
        ('odoo_sh', 'Odoo.sh'),
        ('oec_sh', 'OEC.sh'),
        ('docker', 'Docker'),
        ('odoo_online', 'Odoo Online'),
        ('custom', 'Custom Server'),
        ('other', 'Other'),
    ], string='Kind', required=True, default='other',
        help="Technical category. Odoo.sh / OEC.sh show the project URL, branch "
             "and database; Docker shows the image, compose path and container; "
             "the rest only show the URL and login.")
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    show_infrastructure = fields.Boolean(
        string='Uses an Infrastructure profile', default=True,
        help="When on, environments using this platform show the Infrastructure "
             "(server) link so they can be tied to a server profile. Turn it off "
             "for managed hosting that has no separate server, e.g. Odoo.sh or "
             "Odoo Online.")
    note = fields.Char(string='Note')
