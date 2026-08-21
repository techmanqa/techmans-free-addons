import base64
import hashlib
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover
    Fernet = InvalidToken = None


class PartnerInfrastructure(models.Model):
    _name = 'partner.infrastructure'
    _description = 'Client Infrastructure Profile'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    _partner_uniq = models.Constraint(
        'unique (partner_id)',
        'This client already has an infrastructure profile.',
    )

    partner_id = fields.Many2one('res.partner', string='Client', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company, index=True)

    # ------------------------------------------------------------------
    # Hosting — the top-level marker; drives which section below is shown.
    # ------------------------------------------------------------------
    hosting_type = fields.Selection([
        ('online', 'Online'),
        ('odoo_sh', 'Odoo.sh'),
        ('custom_server', 'Custom Server'),
    ], string='Hosting Type', required=True, default='odoo_sh', tracking=True)

    odoo_sh_url = fields.Char(string='Odoo.sh Project URL', tracking=True)
    odoo_sh_branch = fields.Char(string='Odoo.sh Branch', default='main')
    odoo_sh_database = fields.Char(string='Database Name')

    server_host = fields.Char(string='Server Host / IP', tracking=True)
    server_ssh_port = fields.Integer(string='SSH Port', default=22)
    server_ssh_user = fields.Char(string='SSH User')
    hosting_provider = fields.Char(string='Hosting Provider')

    # ------------------------------------------------------------------
    # Odoo login — always shown, regardless of hosting type.
    # ------------------------------------------------------------------
    odoo_login_url = fields.Char(string='Odoo Login URL', tracking=True)
    odoo_login_email = fields.Char(string='Login Email',
                                   groups='ts_partner_app.group_partner_asset_manager')
    odoo_login_password = fields.Char(string='Login Password', copy=False,
                                      compute='_compute_odoo_login_password',
                                      inverse='_inverse_odoo_login_password',
                                      groups='ts_partner_app.group_partner_asset_manager')
    odoo_login_password_encrypted = fields.Char(string='Login Password (encrypted)', copy=False,
                                                groups='ts_partner_app.group_partner_asset_manager')
    show_odoo_login_password = fields.Boolean(string='Show Login Password', default=False, copy=False,
                                              groups='ts_partner_app.group_partner_asset_manager')

    # ------------------------------------------------------------------
    # GitHub / code repository — always shown.
    # ------------------------------------------------------------------
    github_url = fields.Char(string='Repository URL', tracking=True)
    github_branch = fields.Char(string='GitHub Branch', default='main')
    github_token = fields.Char(string='Access Token', copy=False,
                               compute='_compute_github_token',
                               inverse='_inverse_github_token',
                               groups='ts_partner_app.group_partner_asset_manager',
                               help="Personal Access Token used to grant access to the repository, if any.")
    github_token_encrypted = fields.Char(string='Access Token (encrypted)', copy=False,
                                         groups='ts_partner_app.group_partner_asset_manager')
    show_github_token = fields.Boolean(string='Show Access Token', default=False, copy=False,
                                       groups='ts_partner_app.group_partner_asset_manager')

    notes = fields.Text(string='Notes')
    credential_log_ids = fields.One2many('partner.asset.credential.log', 'infrastructure_id',
                                         string='Credential Access Log',
                                         groups='ts_partner_app.group_partner_asset_manager')

    # ------------------------------------------------------------------
    # Encryption helpers (mirrors partner.asset's credential handling)
    # ------------------------------------------------------------------
    @api.model
    def _get_fernet(self):
        if Fernet is None:
            return None
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret') or ''
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        return Fernet(key)

    def _decrypt_value(self, ciphertext):
        if not ciphertext:
            return False
        fernet = self._get_fernet()
        if fernet is None:
            return ciphertext
        try:
            return fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, Exception):
            return ciphertext

    def _encrypt_value(self, plaintext):
        if not plaintext:
            return False
        fernet = self._get_fernet()
        if fernet is None:
            return plaintext
        return fernet.encrypt(plaintext.encode()).decode()

    def _log_credential_action(self, action, field_name):
        if self.env.context.get('skip_credential_log'):
            return
        self.env['partner.asset.credential.log'].sudo().create([{
            'infrastructure_id': rec.id,
            'user_id': self.env.user.id,
            'action': action,
            'field_name': field_name,
        } for rec in self if rec.id])

    @api.depends('odoo_login_password_encrypted')
    def _compute_odoo_login_password(self):
        for rec in self:
            rec.odoo_login_password = rec._decrypt_value(rec.odoo_login_password_encrypted)

    def _inverse_odoo_login_password(self):
        for rec in self:
            rec.odoo_login_password_encrypted = rec._encrypt_value(rec.odoo_login_password)
        self._log_credential_action('update', 'odoo_login_password')

    @api.depends('github_token_encrypted')
    def _compute_github_token(self):
        for rec in self:
            rec.github_token = rec._decrypt_value(rec.github_token_encrypted)

    def _inverse_github_token(self):
        for rec in self:
            rec.github_token_encrypted = rec._encrypt_value(rec.github_token)
        self._log_credential_action('update', 'github_token')

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def toggle_odoo_login_password(self):
        self.ensure_one()
        self.show_odoo_login_password = not self.show_odoo_login_password
        if self.show_odoo_login_password:
            self._log_credential_action('reveal', 'odoo_login_password')

    def toggle_github_token(self):
        self.ensure_one()
        self.show_github_token = not self.show_github_token
        if self.show_github_token:
            self._log_credential_action('reveal', 'github_token')

    def action_open_odoo_login_url(self):
        self.ensure_one()
        if not self.odoo_login_url:
            return
        return {'type': 'ir.actions.act_url', 'url': self.odoo_login_url, 'target': 'new'}

    def action_open_odoo_sh_url(self):
        self.ensure_one()
        if not self.odoo_sh_url:
            return
        return {'type': 'ir.actions.act_url', 'url': self.odoo_sh_url, 'target': 'new'}

    def action_open_github_url(self):
        self.ensure_one()
        if not self.github_url:
            return
        return {'type': 'ir.actions.act_url', 'url': self.github_url, 'target': 'new'}
