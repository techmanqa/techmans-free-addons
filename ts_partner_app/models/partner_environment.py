import base64
import hashlib
import logging
import socket
import ssl as ssl_lib
from urllib.parse import urlparse

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography import x509
except ImportError:  # pragma: no cover
    Fernet = InvalidToken = x509 = None


class PartnerEnvironment(models.Model):
    """A single Odoo environment of a client (production / staging / ...).

    Infrastructure (``partner.infrastructure``) describes the *server* — one
    per client. Environments describe *Odoo itself* and there can be several
    per client, each optionally pinned to an infrastructure profile and to a
    client asset.
    """
    _name = 'partner.environment'
    _description = 'Client Odoo Environment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'partner_id, sequence, id'

    name = fields.Char(string='Name', required=True, default='Production', tracking=True)
    env_type = fields.Selection([
        ('production', 'Production'),
        ('staging', 'Staging'),
        ('development', 'Development'),
        ('test', 'Test'),
        ('other', 'Other'),
    ], string='Environment Type', required=True, default='production', tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    is_primary = fields.Boolean(
        string='Primary Environment', tracking=True,
        help="The client's main environment. Used by the portal and the PDF "
             "reports when a single environment has to be shown.")

    partner_id = fields.Many2one('res.partner', string='Client', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company, index=True)
    infrastructure_id = fields.Many2one(
        'partner.infrastructure', string='Infrastructure', ondelete='set null', tracking=True,
        help="Server / hosting profile this environment runs on.")
    asset_id = fields.Many2one(
        'partner.asset', string='Client Asset', ondelete='set null',
        help="Client asset (subscription / engagement) this environment belongs to.")

    # ------------------------------------------------------------------
    # Platform — how this environment's Odoo is hosted / packaged. The
    # kind drives which of the fields below are shown.
    # ------------------------------------------------------------------
    platform_id = fields.Many2one('partner.environment.platform', string='Platform', tracking=True)
    platform_kind = fields.Selection(related='platform_id.kind', string='Platform Kind', store=True)
    platform_show_infrastructure = fields.Boolean(
        related='platform_id.show_infrastructure', string='Platform uses infrastructure')

    # Project (Odoo.sh / OEC.sh)
    project_url = fields.Char(string='Project URL', tracking=True)
    project_branch = fields.Char(string='Branch', default='main')
    database_name = fields.Char(string='Database Name')

    # Docker (on a custom server)
    docker_image = fields.Char(string='Docker Image / Tag')
    docker_compose_path = fields.Char(string='Compose / Stack Path',
                                      help="Path to the docker-compose / stack file on the server.")
    docker_container = fields.Char(string='Container Name')

    # ------------------------------------------------------------------
    # Odoo login
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
    # GitHub / code repository
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
    code_repository_branch = fields.Char(string='Code Repository Branch', tracking=True)

    # ------------------------------------------------------------------
    # Version & upgrade tracking
    # ------------------------------------------------------------------
    current_version = fields.Many2one('odoo.version', string='Current Odoo Version', tracking=True)
    latest_version = fields.Many2one('odoo.version', string='Latest Available Version', tracking=True)
    last_upgrade_date = fields.Date(string='Last Upgrade Date', tracking=True)
    upgrade_available = fields.Boolean(
        string='Upgrade Available', compute='_compute_upgrade_available', store=True,
        help="Current Odoo Version is older than the Latest Available Version.")
    technical_debt_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], string='Technical Debt Level', tracking=True)

    custom_module_ids = fields.One2many('partner.asset.custom.module', 'environment_id',
                                        string='Custom Modules Installed')
    native_module_ids = fields.Many2many('partner.asset.native.module', string='Native Odoo Apps Used',
                                         help="Standard Odoo apps this environment runs (Sales, "
                                              "Inventory, Accounting...). For bespoke development, use "
                                              "Custom Modules instead.")

    # ------------------------------------------------------------------
    # Access — encrypted at rest (Fernet, key derived from the database
    # secret). Manager-only; reveals and updates go to the audit log.
    # ------------------------------------------------------------------
    url = fields.Char(string='URL / Link', tracking=True)
    login_email = fields.Char(string='Username / Login email',
                              groups='ts_partner_app.group_partner_asset_manager')
    password = fields.Char(string='Password', copy=False,
                           compute='_compute_password', inverse='_inverse_password',
                           groups='ts_partner_app.group_partner_asset_manager')
    password_encrypted = fields.Char(string='Password (encrypted)', copy=False,
                                     groups='ts_partner_app.group_partner_asset_manager')
    show_password = fields.Boolean(string='Show Password', default=False, copy=False,
                                   groups='ts_partner_app.group_partner_asset_manager')
    url2 = fields.Char(string='URL / Link 2', tracking=True)
    login_email2 = fields.Char(string='Username / Login email 2',
                               groups='ts_partner_app.group_partner_asset_manager')
    password2 = fields.Char(string='Password 2', copy=False,
                            compute='_compute_password2', inverse='_inverse_password2',
                            groups='ts_partner_app.group_partner_asset_manager')
    password2_encrypted = fields.Char(string='Password 2 (encrypted)', copy=False,
                                      groups='ts_partner_app.group_partner_asset_manager')
    show_password2 = fields.Boolean(string='Show Password 2', default=False, copy=False,
                                    groups='ts_partner_app.group_partner_asset_manager')

    # ------------------------------------------------------------------
    # Live health monitoring (SSL / uptime) + backup & risk
    # ------------------------------------------------------------------
    website_up = fields.Boolean(string='Website Reachable', readonly=True, copy=False)
    last_health_check = fields.Datetime(string='Last Health Check', readonly=True, copy=False)
    ssl_expiry_date = fields.Date(string='SSL Certificate Expiry', readonly=True, copy=False, tracking=True)
    ssl_days_left = fields.Integer(string='SSL Days Left', compute='_compute_ssl_days_left')
    last_backup_check = fields.Date(string='Last Backup Check Date', tracking=True)
    backup_verified = fields.Boolean(string='Backup Verified', tracking=True)
    monitoring_active = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
    ], string='Monitoring Active', default='no', tracking=True)
    dr_plan_documented = fields.Boolean(string='Disaster Recovery Plan Documented', tracking=True)
    risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Risk Level', default='low', tracking=True)

    notes = fields.Text(string='Notes')
    credential_log_ids = fields.One2many('partner.asset.credential.log', 'environment_id',
                                         string='Credential Access Log',
                                         groups='ts_partner_app.group_partner_asset_manager')

    # ------------------------------------------------------------------
    # Computes / constraints
    # ------------------------------------------------------------------
    @api.depends('name', 'partner_id.display_name')
    def _compute_display_name(self):
        for env in self:
            if env.partner_id:
                env.display_name = "%s / %s" % (env.partner_id.display_name, env.name or '')
            else:
                env.display_name = env.name or _('New Environment')

    @api.depends('current_version.sequence', 'latest_version.sequence')
    def _compute_upgrade_available(self):
        for env in self:
            env.upgrade_available = bool(
                env.current_version and env.latest_version
                and env.current_version.sequence < env.latest_version.sequence
            )

    @api.constrains('is_primary', 'partner_id')
    def _check_single_primary(self):
        for env in self.filtered('is_primary'):
            dup = self.search([
                ('partner_id', '=', env.partner_id.id),
                ('is_primary', '=', True),
                ('id', '!=', env.id),
            ], limit=1)
            if dup:
                raise ValidationError(_(
                    "%(partner)s already has a primary environment (%(env)s). "
                    "Only one environment can be marked primary.",
                    partner=env.partner_id.display_name, env=dup.name))

    @api.model_create_multi
    def create(self, vals_list):
        envs = super().create(vals_list)
        for env in envs:
            if not env.is_primary and not self.search_count([
                ('partner_id', '=', env.partner_id.id), ('is_primary', '=', True),
            ]):
                env.is_primary = True
        return envs

    # ------------------------------------------------------------------
    # Encryption helpers (mirrors partner.infrastructure / partner.asset)
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
            'environment_id': rec.id,
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

    @api.depends('password_encrypted')
    def _compute_password(self):
        for rec in self:
            rec.password = rec._decrypt_value(rec.password_encrypted)

    def _inverse_password(self):
        for rec in self:
            rec.password_encrypted = rec._encrypt_value(rec.password)
        self._log_credential_action('update', 'password')

    @api.depends('password2_encrypted')
    def _compute_password2(self):
        for rec in self:
            rec.password2 = rec._decrypt_value(rec.password2_encrypted)

    def _inverse_password2(self):
        for rec in self:
            rec.password2_encrypted = rec._encrypt_value(rec.password2)
        self._log_credential_action('update', 'password2')

    @api.depends('ssl_expiry_date')
    def _compute_ssl_days_left(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.ssl_days_left = (rec.ssl_expiry_date - today).days if rec.ssl_expiry_date else 0

    # ------------------------------------------------------------------
    # Live health checks (SSL / uptime)
    # ------------------------------------------------------------------
    def _get_health_endpoint(self):
        self.ensure_one()
        url = (self.url or '').strip()
        if not url:
            return None, None, None
        if '://' not in url:
            url = 'https://' + url
        parsed = urlparse(url)
        if not parsed.hostname:
            return None, None, None
        use_tls = parsed.scheme != 'http'
        port = parsed.port or (443 if use_tls else 80)
        return parsed.hostname, port, use_tls

    def action_check_health(self):
        """Connect to the environment's URL: uptime + real SSL certificate
        expiry. Escalates risk_level to High when the site is down or the
        certificate expires in under 14 days (never downgrades automatically).
        When the environment is linked to a client asset still in the "New"
        stage, a first successful check promotes that asset to "Running"."""
        today = fields.Date.context_today(self)
        new_stage = self.env.ref('ts_partner_app.stage_new', raise_if_not_found=False)
        running_stage = self.env.ref('ts_partner_app.stage_running', raise_if_not_found=False)
        manager_group = self.env.ref('ts_partner_app.group_partner_asset_manager', raise_if_not_found=False)
        manager_partners = manager_group.user_ids.partner_id if manager_group else self.env['res.partner']
        for rec in self:
            host, port, use_tls = rec._get_health_endpoint()
            if not host:
                continue
            up = False
            ssl_exp = rec.ssl_expiry_date
            try:
                with socket.create_connection((host, port), timeout=10) as sock:
                    up = True
                    if use_tls and x509 is not None:
                        ctx = ssl_lib.SSLContext(ssl_lib.PROTOCOL_TLS_CLIENT)
                        ctx.check_hostname = False
                        ctx.verify_mode = ssl_lib.CERT_NONE  # we only read the expiry
                        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                            der = ssock.getpeercert(True)
                            cert = x509.load_der_x509_certificate(der)
                            not_after = getattr(cert, 'not_valid_after_utc', None) or cert.not_valid_after
                            ssl_exp = not_after.date()
            except Exception as exc:
                _logger.info("Health check failed for environment %s (%s): %s",
                             rec.display_name, host, exc)
                up = False
            vals = {
                'website_up': up,
                'last_health_check': fields.Datetime.now(),
                'ssl_expiry_date': ssl_exp,
            }
            alerts = []
            if not up:
                alerts.append(_("the site is unreachable"))
            if ssl_exp and (ssl_exp - today).days < 14:
                alerts.append(_("the SSL certificate expires on %s", ssl_exp))
            if alerts and rec.risk_level != 'high':
                vals['risk_level'] = 'high'
                notify_partners = manager_partners | (
                    rec.asset_id.user_id.partner_id if rec.asset_id.user_id else self.env['res.partner'])
                rec.message_post(
                    body=_("Health check escalated risk to High: %s.", " and ".join(alerts)),
                    partner_ids=notify_partners.ids,
                )
            asset = rec.asset_id
            provisioned = (up and new_stage and running_stage
                           and asset and asset.stage_id == new_stage)
            rec.write(vals)
            if provisioned:
                asset.write({'stage_id': running_stage.id, 'state': 'running'})
                asset.message_post(body=_(
                    "Provisioning confirmed — %s is live. Moved from New to Running.",
                    rec.display_name))
        return True

    def _cron_check_environment_health(self):
        envs = self.search([('url', '!=', False)])
        for rec in envs:
            if rec.asset_id and rec.asset_id.state == 'closed':
                continue
            try:
                rec.action_check_health()
            except Exception as exc:  # never let one environment break the cron
                _logger.error("Health check crashed for environment %s: %s",
                              rec.display_name, exc)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def toggle_password(self):
        self.ensure_one()
        self.show_password = not self.show_password
        if self.show_password:
            self._log_credential_action('reveal', 'password')

    def toggle_password2(self):
        self.ensure_one()
        self.show_password2 = not self.show_password2
        if self.show_password2:
            self._log_credential_action('reveal', 'password2')

    def action_open_url(self):
        self.ensure_one()
        if not self.url:
            return
        return {'type': 'ir.actions.act_url', 'url': self.url, 'target': 'new'}

    def action_open_url2(self):
        self.ensure_one()
        if not self.url2:
            return
        return {'type': 'ir.actions.act_url', 'url': self.url2, 'target': 'new'}

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

    def action_open_project_url(self):
        self.ensure_one()
        if not self.project_url:
            return
        return {'type': 'ir.actions.act_url', 'url': self.project_url, 'target': 'new'}

    def action_open_odoo_login_url(self):
        self.ensure_one()
        if not self.odoo_login_url:
            return
        return {'type': 'ir.actions.act_url', 'url': self.odoo_login_url, 'target': 'new'}

    def action_open_github_url(self):
        self.ensure_one()
        if not self.github_url:
            return
        return {'type': 'ir.actions.act_url', 'url': self.github_url, 'target': 'new'}
