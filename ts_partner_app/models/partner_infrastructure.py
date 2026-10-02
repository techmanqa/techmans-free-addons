import base64
import hashlib
import logging

from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from . import ssh_utils

_logger = logging.getLogger(__name__)

# One round-trip that prints CPU count, memory, disk and uptime. Assumes a
# Linux host with GNU coreutils.
SERVER_RESOURCE_COMMAND = (
    "echo '=== CPU ==='; nproc; "
    "echo '=== MEMORY ==='; free -h; "
    "echo '=== DISK ==='; df -h /; "
    "echo '=== UPTIME ==='; uptime"
)

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

    server_host = fields.Char(string='Server Host / IP', tracking=True)
    server_ssh_port = fields.Integer(string='SSH Port', default=22)
    server_ssh_user = fields.Char(string='SSH User')
    hosting_provider_id = fields.Many2one('partner.hosting.provider', string='Hosting Provider',
                                          ondelete='restrict')

    # ------------------------------------------------------------------
    # Custom Server — SSH management (only relevant when hosting_type ==
    # 'custom_server'). Reuses server_host / server_ssh_port / server_ssh_user
    # above as the connection target.
    # ------------------------------------------------------------------
    server_auth_type = fields.Selection([
        ('password', 'Password'),
        ('key', 'SSH Key'),
    ], string='SSH Authentication', default='password')

    server_password = fields.Char(string='SSH Password', copy=False,
                                  compute='_compute_server_password',
                                  inverse='_inverse_server_password',
                                  groups='ts_partner_app.group_partner_asset_manager')
    server_password_encrypted = fields.Char(string='SSH Password (encrypted)', copy=False,
                                            groups='ts_partner_app.group_partner_asset_manager')
    show_server_password = fields.Boolean(string='Show SSH Password', default=False, copy=False,
                                          groups='ts_partner_app.group_partner_asset_manager')

    server_private_key = fields.Text(string='SSH Private Key', copy=False,
                                     compute='_compute_server_private_key',
                                     inverse='_inverse_server_private_key',
                                     groups='ts_partner_app.group_partner_asset_manager',
                                     help="PEM/OpenSSH private key used for key-based authentication.")
    server_private_key_encrypted = fields.Text(string='SSH Private Key (encrypted)', copy=False,
                                               groups='ts_partner_app.group_partner_asset_manager')
    server_key_passphrase = fields.Char(string='Key Passphrase', copy=False,
                                        compute='_compute_server_key_passphrase',
                                        inverse='_inverse_server_key_passphrase',
                                        groups='ts_partner_app.group_partner_asset_manager')
    server_key_passphrase_encrypted = fields.Char(string='Key Passphrase (encrypted)', copy=False,
                                                  groups='ts_partner_app.group_partner_asset_manager')

    server_restart_command = fields.Char(string='Restart Command',
                                         help="Command sent by the Restart button, e.g. "
                                              "'sudo systemctl restart odoo'.")
    server_status = fields.Selection([
        ('unknown', 'Unknown'),
        ('online', 'Online'),
        ('error', 'Error'),
    ], string='Connection Status', default='unknown', tracking=True, copy=False)
    server_last_check = fields.Datetime(string='Last Check', readonly=True, copy=False)
    server_resource_info = fields.Text(string='Server Resources', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Odoo environments running on this server — the Odoo-specific details
    # (Odoo.sh, logins, repositories, versions, modules) live there.
    # ------------------------------------------------------------------
    environment_ids = fields.One2many('partner.environment', 'infrastructure_id',
                                      string='Environments')
    environment_count = fields.Integer(string='Environments',
                                       compute='_compute_environment_count')

    notes = fields.Text(string='Notes')
    credential_log_ids = fields.One2many('partner.asset.credential.log', 'infrastructure_id',
                                         string='Credential Access Log',
                                         groups='ts_partner_app.group_partner_asset_manager')

    @api.depends('environment_ids')
    def _compute_environment_count(self):
        for rec in self:
            rec.environment_count = len(rec.environment_ids)

    # ------------------------------------------------------------------
    # Encryption helpers (mirrors partner.asset's credential handling)
    # ------------------------------------------------------------------
    @api.model
    def _get_fernet(self):
        if Fernet is None:
            return None
        secret = self.env['ir.config_parameter'].sudo().get_str('database.secret')
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

    @api.depends('server_password_encrypted')
    def _compute_server_password(self):
        for rec in self:
            rec.server_password = rec._decrypt_value(rec.server_password_encrypted)

    def _inverse_server_password(self):
        for rec in self:
            rec.server_password_encrypted = rec._encrypt_value(rec.server_password)
        self._log_credential_action('update', 'server_password')

    @api.depends('server_private_key_encrypted')
    def _compute_server_private_key(self):
        for rec in self:
            rec.server_private_key = rec._decrypt_value(rec.server_private_key_encrypted)

    def _inverse_server_private_key(self):
        for rec in self:
            rec.server_private_key_encrypted = rec._encrypt_value(rec.server_private_key)
        self._log_credential_action('update', 'server_private_key')

    @api.depends('server_key_passphrase_encrypted')
    def _compute_server_key_passphrase(self):
        for rec in self:
            rec.server_key_passphrase = rec._decrypt_value(rec.server_key_passphrase_encrypted)

    def _inverse_server_key_passphrase(self):
        for rec in self:
            rec.server_key_passphrase_encrypted = rec._encrypt_value(rec.server_key_passphrase)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def toggle_server_password(self):
        self.ensure_one()
        self.show_server_password = not self.show_server_password
        if self.show_server_password:
            self._log_credential_action('reveal', 'server_password')

    # ------------------------------------------------------------------
    # Custom Server — SSH actions
    # ------------------------------------------------------------------
    def _ssh_run(self, command, timeout=ssh_utils.DEFAULT_TIMEOUT):
        """Run a command on this profile's custom server over SSH."""
        self.ensure_one()
        return ssh_utils.run_command(
            command,
            host=self.server_host,
            port=self.server_ssh_port,
            username=self.server_ssh_user,
            auth_type=self.server_auth_type or 'password',
            password=self.server_password,
            private_key=self.server_private_key,
            passphrase=self.server_key_passphrase,
            timeout=timeout,
        )

    def _ssh_notify(self, message, notif_type='success', reload=True):
        params = {'message': message, 'type': notif_type, 'sticky': notif_type == 'danger'}
        if reload:
            params['next'] = {'type': 'ir.actions.client', 'tag': 'soft_reload'}
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': params}

    def _ssh_mark_failed(self, error):
        self.write({'server_status': 'error', 'server_last_check': fields.Datetime.now()})
        self.message_post(body=_("SSH action failed: %s", error))
        return self._ssh_notify(str(error), 'danger')

    def action_server_test_connection(self):
        self.ensure_one()
        try:
            self._ssh_run('true', timeout=10)
        except UserError as err:
            return self._ssh_mark_failed(err)
        self.write({'server_status': 'online', 'server_last_check': fields.Datetime.now()})
        self.message_post(body=_("Connection test succeeded (%s).", self.server_host))
        return self._ssh_notify(_("SSH connection successful."))

    def action_server_fetch_resources(self):
        self.ensure_one()
        try:
            _exit, out, err = self._ssh_run(SERVER_RESOURCE_COMMAND, timeout=15)
        except UserError as exc:
            return self._ssh_mark_failed(exc)
        info = (out or '').strip()
        if (err or '').strip():
            info += "\n\n[stderr]\n" + err.strip()
        info = info or _("(no output)")
        self.write({
            'server_resource_info': info,
            'server_last_check': fields.Datetime.now(),
            'server_status': 'online',
        })
        self.message_post(body=Markup("%s<pre>%s</pre>") % (
            _("Fetched resource information from %s:", self.server_host),
            info,
        ))
        return self._ssh_notify(_("Resources updated. Fetched stats from server."))

    def action_server_run_command(self):
        self.ensure_one()
        return {
            'name': _("Run Command"),
            'type': 'ir.actions.act_window',
            'res_model': 'partner.infrastructure.command.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_infrastructure_id': self.id},
        }

    def action_server_restart(self):
        self.ensure_one()
        if not self.server_restart_command:
            raise UserError(_("No restart command is configured for this server."))
        self._log_credential_action('reveal', 'server_restart_command')
        try:
            _exit, out, err = self._ssh_run(self.server_restart_command, timeout=20)
        except UserError as exc:
            # Restarting the service frequently drops the SSH session before a
            # result comes back -- treat that as "sent", not a hard failure.
            self.message_post(body=_(
                "Restart command sent: %(cmd)s\n"
                "No result returned before the connection closed (expected when "
                "the service restarts): %(err)s",
                cmd=self.server_restart_command, err=exc,
            ))
            return self._ssh_notify(
                _("Restart triggered. Connection closed before a result returned."), 'warning')
        output = ((out or '') + (("\n" + err) if (err or '').strip() else '')).strip()
        body = _("Restart command run: %s", self.server_restart_command)
        if output:
            body = Markup("%s<pre>%s</pre>") % (body, output)
        self.message_post(body=body)
        return self._ssh_notify(_("Restart triggered. Command executed."))

    def action_view_environments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Environments"),
            'res_model': 'partner.environment',
            'view_mode': 'list,form',
            'domain': [('infrastructure_id', '=', self.id)],
            'context': {
                'default_infrastructure_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
        }
