import base64
import hashlib
import logging
import socket
import ssl as ssl_lib
from datetime import datetime, timedelta
from urllib.parse import urlparse

from odoo import models, fields, api, _
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography import x509
except ImportError:  # pragma: no cover
    Fernet = InvalidToken = x509 = None
    _logger.warning("The 'cryptography' python package is required by ts_partner_app.")


class PartnerAsset(models.Model):
    _name = 'partner.asset'
    _description = 'Client-Related Asset'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name / Label', required=True, tracking=True, readonly=True,
                      help="Automatically set to the Customer's Client Reference and asset Type "
                           "once both are chosen (kept unique across a customer's assets).")
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company, index=True)
    type = fields.Selection([
        ('online', 'Online'),
        ('odoo_sh', 'Odoo.sh'),
        ('custom', 'Custom'),
    ], string='Type', required=True, tracking=True)
    tag_ids = fields.Many2many('partner.asset.tag', string='Tags')
    color = fields.Integer(string='Color Index', compute='_compute_color', store=True, readonly=False,
                           help="Defaults to the stage's Kanban color; override freely per card.")

    # ------------------------------------------------------------------
    # Credentials — encrypted at rest (Fernet, key derived from the
    # database secret). The user-facing fields are non-stored computes;
    # only the encrypted ciphertext hits the database. Restricted to
    # Asset Managers at the ORM level. No tracking (would leak values
    # into the chatter). Reveals and updates are written to an audit log.
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
    credential_log_ids = fields.One2many('partner.asset.credential.log', 'asset_id',
                                         string='Credential Access Log',
                                         groups='ts_partner_app.group_partner_asset_manager')

    subscription_number = fields.Char(string='Subscription Number', tracking=True)
    start_date = fields.Date(string='Start Date', tracking=True)
    end_date = fields.Date(string='End Date', tracking=True)
    reminder_days = fields.Integer(
        string='Remind (days before end)', default=60,
        help="Number of days before the End Date at which the expiry reminder "
             "is triggered. Used to compute the Expiry (reminder) date below.")
    renewal_period = fields.Integer(
        string='Renewal Period (months)', default=12,
        help="When the linked renewal Sale Order is confirmed, the End Date is "
             "extended by this many months.")
    expiry_date = fields.Date(
        string='Expiry date', tracking=True,
        compute='_compute_expiry_date', store=True, readonly=False,
        help="Date on which the expiry reminder fires. Automatically computed "
             "as End Date - Reminder Days, but can be overridden manually.")
    expiry_notified = fields.Boolean(string='Expiry Notification Sent', default=False, copy=False)
    notify_client_on_expiry = fields.Boolean(
        string='Email Client on Expiry', default=True,
        help="Send the client a renewal reminder email (in addition to the internal "
             "reminder to the Responsible User) when this asset reaches its expiry date.")
    sale_order_id = fields.Many2one('sale.order', string='Sale Order / Subscription', tracking=True)
    campaign_id = fields.Many2one('utm.campaign', string='Campaign', tracking=True,
                                  help="CRM/marketing campaign this asset is linked to (e.g. the "
                                       "campaign that brought in this client or this upsell).")
    user_id = fields.Many2one('res.users', string='Responsible User',
                              default=lambda self: self.env.user, tracking=True)
    stage_id = fields.Many2one('partner.asset.stage', string='Stage', tracking=True, index=True, copy=False,
                               default=lambda self: self.env['partner.asset.stage'].search([], limit=1, order='sequence'),
                               group_expand='_read_group_stage_ids')
    state = fields.Selection([
        ('new', 'New'),
        ('running', 'Running'),
        ('to_renew', 'To Renew'),
        ('closed', 'Closed')
    ], string='Status', default='new', tracking=True)
    notes = fields.Text(string='Notes')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: self.env.company.currency_id)
    server_cost = fields.Monetary(string='Monthly Server Cost', currency_field='currency_id', tracking=True)
    server_cost_billed = fields.Boolean(
        string='Billed by Us', default=False, tracking=True,
        help="Included in Gross Margin only if checked. Leave unchecked when the client pays "
             "the server directly (their own hosting/provider account) rather than through us.")
    license_cost = fields.Monetary(string='License Cost (per license)', currency_field='currency_id', tracking=True,
                                   help="Monthly cost of a single license. Multiplied by Licenses "
                                        "(Version & Upgrade tab) to get the Total License Cost below.")
    license_cost_billed = fields.Boolean(
        string='Billed by Us', default=False, tracking=True,
        help="Included in Gross Margin only if checked. Leave unchecked when the client pays "
             "Odoo directly for licenses, which is the common case.")
    license_cost_total = fields.Monetary(string='Total License Cost', compute='_compute_license_cost_total',
                                         currency_field='currency_id', store=True)
    backup_cost = fields.Monetary(string='Backup Cost', currency_field='currency_id', tracking=True)
    backup_cost_billed = fields.Boolean(
        string='Billed by Us', default=False, tracking=True,
        help="Included in Gross Margin only if checked. Leave unchecked when this is Odoo.sh "
             "storage (or similar) that the client pays directly rather than through us.")
    maintenance_cost = fields.Monetary(string='Maintenance Cost', currency_field='currency_id', tracking=True)
    maintenance_cost_billed = fields.Boolean(
        string='Billed by Us', default=True, tracking=True,
        help="Included in Gross Margin only if checked. Maintenance is normally billed by us "
             "when applicable, so this defaults on.")
    external_services_cost = fields.Monetary(string='External Services Cost', currency_field='currency_id', tracking=True)
    external_services_cost_billed = fields.Boolean(
        string='Billed by Us', default=False, tracking=True,
        help="Included in Gross Margin only if checked. Leave unchecked when the client pays "
             "this third-party service directly.")
    infra_monthly_cost = fields.Monetary(string='Infra Monthly Cost', compute='_compute_infra_monthly_cost',
                                         currency_field='currency_id', store=True, tracking=True,
                                         help="Sum of only the costs above marked 'Billed by Us' — "
                                              "what actually flows through us, used for Gross Margin.")
    monthly_billing_client = fields.Monetary(string='Monthly Billing to Client',
                                             currency_field='currency_id', tracking=True)
    gross_margin = fields.Monetary(string='Gross Margin', compute='_compute_gross_margin',
                                   currency_field='currency_id', store=True)
    margin_pct = fields.Float(string='Margin %', compute='_compute_gross_margin', store=True,
                              aggregator='avg', help="Gross margin as a percentage of client billing.")
    client_it_contact = fields.Many2one('res.partner', string='Client IT contact', tracking=True,
                                         domain="[('id', 'child_of', partner_id)] if partner_id else []")
    decision_maker_contact = fields.Many2one('res.partner', string='Decision maker', tracking=True,
                                              domain="[('id', 'child_of', partner_id)] if partner_id else []")
    emergency_contact = fields.Many2one('res.partner', string='Emergency contact', tracking=True,
                                         domain="[('id', 'child_of', partner_id)] if partner_id else []")
    emergency_contact_phone = fields.Char(related='emergency_contact.phone', string='Emergency Phone', readonly=True)
    escalation_path = fields.Text(string='Escalation path', tracking=True)

    # Backup & Risk Monitoring
    last_backup_check = fields.Date(string='Last Backup Check Date', tracking=True)
    backup_verified = fields.Boolean(string='Backup Verified', tracking=True)
    monitoring_active = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No')
    ], string='Monitoring Active', default='no', tracking=True)
    dr_plan_documented = fields.Boolean(string='Disaster Recovery Plan Documented', tracking=True)
    risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High')
    ], string='Risk Level', default='low', tracking=True)

    # Live health monitoring (SSL / uptime)
    website_up = fields.Boolean(string='Website Reachable', readonly=True, copy=False)
    last_health_check = fields.Datetime(string='Last Health Check', readonly=True, copy=False)
    ssl_expiry_date = fields.Date(string='SSL Certificate Expiry', readonly=True, copy=False, tracking=True)
    ssl_days_left = fields.Integer(string='SSL Days Left', compute='_compute_ssl_days_left')

    # Version & Upgrade Tracking
    current_version = fields.Char(string='Current Odoo Version', tracking=True)
    latest_version = fields.Char(string='Latest Available Version', tracking=True)
    last_upgrade_date = fields.Date(string='Last Upgrade Date', tracking=True)
    license_count = fields.Integer(string='Licenses', tracking=True,
                                   help="Number of user licenses / seats this client is on.")
    native_module_ids = fields.Many2many('partner.asset.native.module', string='Native Odoo Apps Used',
                                         help="Standard Odoo apps this client uses (Sales, Inventory, "
                                              "Accounting...). For bespoke development, use Custom "
                                              "Modules below instead.")
    custom_module_ids = fields.One2many('partner.asset.custom.module', 'asset_id', string='Custom Modules Installed')
    code_repository_branch = fields.Char(string='Code Repository Branch', tracking=True)
    technical_debt_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical')
    ], string='Technical Debt Level', tracking=True)

    # Project integration
    task_ids = fields.One2many('project.task', 'asset_id', string='Tasks')
    task_count = fields.Integer(compute='_compute_task_count', string='Task Count')
    client_project_id = fields.Many2one('project.project', compute='_compute_client_project',
                                        string='Client Project')
    client_project_task_count = fields.Integer(compute='_compute_client_project',
                                                string='Client Project Task Count')
    partner_infrastructure_count = fields.Integer(compute='_compute_partner_infrastructure',
                                                   string='Client Infrastructure Count')

    # Billing (one-off renewal quotes and ad-hoc invoices created from this asset)
    invoice_ids = fields.Many2many('account.move', compute='_compute_invoices', string='Invoices')
    invoice_count = fields.Integer(compute='_compute_invoices', string='Invoice Count')

    # ------------------------------------------------------------------
    # Encryption helpers
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
            # Legacy / foreign value stored before encryption was introduced.
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
            'asset_id': rec.id,
            'user_id': self.env.user.id,
            'action': action,
            'field_name': field_name,
        } for rec in self if rec.id])

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

    # ------------------------------------------------------------------
    # Onchange
    # ------------------------------------------------------------------
    @api.onchange('partner_id', 'type')
    def _onchange_partner_id_name(self):
        if self.partner_id:
            count = self._count_existing_assets(self.partner_id.id, self.type)
            self.name = self._asset_name_for(self.partner_id, self.type, existing_count=count)

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        order = self.sale_order_id
        if not order:
            return
        if order.partner_id:
            self.partner_id = order.partner_id

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('stage_id')
    def _compute_color(self):
        for record in self:
            record.color = record.stage_id.color

    @api.depends('license_cost', 'license_count')
    def _compute_license_cost_total(self):
        for record in self:
            record.license_cost_total = record.license_cost * record.license_count

    @api.depends('server_cost', 'server_cost_billed',
                'license_cost_total', 'license_cost_billed',
                'backup_cost', 'backup_cost_billed',
                'maintenance_cost', 'maintenance_cost_billed',
                'external_services_cost', 'external_services_cost_billed')
    def _compute_infra_monthly_cost(self):
        for record in self:
            record.infra_monthly_cost = (
                (record.server_cost if record.server_cost_billed else 0)
                + (record.license_cost_total if record.license_cost_billed else 0)
                + (record.backup_cost if record.backup_cost_billed else 0)
                + (record.maintenance_cost if record.maintenance_cost_billed else 0)
                + (record.external_services_cost if record.external_services_cost_billed else 0)
            )

    @api.depends('partner_id.infrastructure_id')
    def _compute_partner_infrastructure(self):
        for record in self:
            record.partner_infrastructure_count = len(record.partner_id.infrastructure_id)

    @api.depends('infra_monthly_cost', 'monthly_billing_client')
    def _compute_gross_margin(self):
        for record in self:
            record.gross_margin = record.monthly_billing_client - record.infra_monthly_cost
            record.margin_pct = (record.gross_margin / record.monthly_billing_client * 100.0
                                 ) if record.monthly_billing_client else 0.0

    @api.depends('end_date', 'reminder_days')
    def _compute_expiry_date(self):
        for record in self:
            if record.end_date:
                record.expiry_date = record.end_date - timedelta(days=record.reminder_days or 60)
            else:
                record.expiry_date = False

    @api.depends('ssl_expiry_date')
    def _compute_ssl_days_left(self):
        today = fields.Date.context_today(self)
        for record in self:
            record.ssl_days_left = (record.ssl_expiry_date - today).days if record.ssl_expiry_date else 0

    def _compute_task_count(self):
        counts = {
            asset.id: count
            for asset, count in self.env['project.task']._read_group(
                [('asset_id', 'in', self.ids)], groupby=['asset_id'], aggregates=['__count'])
        }
        for record in self:
            record.task_count = counts.get(record.id, 0)

    def _compute_client_project(self):
        client_app_tag = self.env.ref('ts_partner_app.project_tag_client_app', raise_if_not_found=False)
        partner_ids = self.mapped('partner_id').ids
        projects = self.env['project.project'].search([
            ('partner_id', 'in', partner_ids),
            ('tag_ids', 'in', client_app_tag.id if client_app_tag else 0),
        ])
        project_by_partner = {project.partner_id.id: project for project in projects}
        task_counts = {
            project.id: count
            for project, count in self.env['project.task']._read_group(
                [('project_id', 'in', projects.ids)], groupby=['project_id'], aggregates=['__count'])
        }
        for record in self:
            project = project_by_partner.get(record.partner_id.id)
            record.client_project_id = project.id if project else False
            record.client_project_task_count = task_counts.get(project.id, 0) if project else 0

    def _compute_invoices(self):
        orders = self.env['sale.order'].search([('asset_id', 'in', self.ids)])
        invoices_by_asset = {}
        for order in orders:
            invoices_by_asset.setdefault(order.asset_id.id, self.env['account.move'])
            invoices_by_asset[order.asset_id.id] |= order.invoice_ids
        for record in self:
            invoices = invoices_by_asset.get(record.id, self.env['account.move'])
            record.invoice_ids = invoices
            record.invoice_count = len(invoices)

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return stages.search([])

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------
    _STAGE_STATE_XMLIDS = (
        ('ts_partner_app.stage_new', 'new'),
        ('ts_partner_app.stage_running', 'running'),
        ('ts_partner_app.stage_to_renew', 'to_renew'),
        ('ts_partner_app.stage_closed', 'closed'),
    )

    def _asset_name_for(self, partner, type_value, existing_count=0):
        base = partner.client_ref or partner.name or ''
        if not base:
            return base
        type_label = dict(self._fields['type']._description_selection(self.env)).get(type_value)
        name = f"{base} - {type_label}" if type_label else base
        return f"{name} ({existing_count + 1})" if existing_count else name

    def _count_existing_assets(self, partner_id, type_value, exclude_ids=()):
        domain = [('partner_id', '=', partner_id), ('type', '=', type_value)]
        if exclude_ids:
            domain.append(('id', 'not in', list(exclude_ids)))
        return self.env['partner.asset'].search_count(domain)

    @api.model_create_multi
    def create(self, vals_list):
        batch_counts = {}
        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            if partner:
                key = (partner.id, vals.get('type'))
                count = batch_counts.get(key)
                if count is None:
                    count = self._count_existing_assets(*key)
                vals['name'] = self._asset_name_for(partner, vals.get('type'), existing_count=count)
                batch_counts[key] = count + 1
        return super().create(vals_list)

    def write(self, vals):
        if ('end_date' in vals or 'expiry_date' in vals) and 'expiry_notified' not in vals:
            vals['expiry_notified'] = False
        # Keep state and stage_id in sync when only one of them is changed directly
        # (statusbar click, Kanban drag, or a plain write from anywhere else) instead of
        # via the cron/health-check paths, which already set both together deliberately.
        # Header button visibility, portal badges, etc. all key off state, so letting it
        # silently fall out of sync with the stage is a real bug, not a cosmetic one.
        if vals.get('stage_id') and 'state' not in vals:
            state = self._state_for_stage_id(vals['stage_id'])
            if state:
                vals['state'] = state
        elif vals.get('state') and 'stage_id' not in vals:
            stage_id = self._stage_id_for_state(vals['state'])
            if stage_id:
                vals['stage_id'] = stage_id
        result = super().write(vals)
        # partner_id/type feed the auto-generated name; a single vals dict can't hold a
        # different name per record, so recompute and (re)write it per record once the
        # new partner_id/type values above are actually in place. All of self is excluded
        # from the existing-count baseline (and counted sequentially as we go) since every
        # record in this batch was just reassigned together.
        if 'partner_id' in vals or 'type' in vals:
            batch_counts = {}
            for record in self.sorted('id'):
                key = (record.partner_id.id, record.type)
                count = batch_counts.get(key)
                if count is None:
                    count = self._count_existing_assets(*key, exclude_ids=self.ids)
                new_name = record._asset_name_for(record.partner_id, record.type, existing_count=count)
                batch_counts[key] = count + 1
                if new_name and new_name != record.name:
                    super(PartnerAsset, record).write({'name': new_name})
        return result

    def _state_for_stage_id(self, stage_id):
        for xmlid, state in self._STAGE_STATE_XMLIDS:
            stage = self.env.ref(xmlid, raise_if_not_found=False)
            if stage and stage.id == stage_id:
                return state
        return False

    def _stage_id_for_state(self, state):
        for xmlid, mapped_state in self._STAGE_STATE_XMLIDS:
            if mapped_state == state:
                stage = self.env.ref(xmlid, raise_if_not_found=False)
                return stage.id if stage else False
        return False

    # ------------------------------------------------------------------
    # Expiry engine (cron)
    # ------------------------------------------------------------------
    def _cron_send_expiry_notifications(self):
        today = fields.Date.context_today(self)
        assets = self.search([
            ('expiry_date', '!=', False),
            ('expiry_date', '<=', today),
            ('state', '!=', 'closed'),
            ('expiry_notified', '=', False),
        ])
        if not assets:
            return
        to_renew_stage = self.env.ref('ts_partner_app.stage_to_renew', raise_if_not_found=False)
        template = self.env.ref('ts_partner_app.mail_template_asset_expiry', raise_if_not_found=False)
        client_template = self.env.ref('ts_partner_app.mail_template_asset_expiry_client',
                                        raise_if_not_found=False)
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        for asset in assets:
            asset.message_post(
                body=_("Reminder: the asset '%(name)s' is approaching its end date (%(date)s).",
                       name=asset.name, date=asset.end_date or asset.expiry_date),
                subtype_xmlid='mail.mt_comment',
                partner_ids=asset.user_id.partner_id.ids if asset.user_id else [],
            )
            if asset.user_id and activity_type:
                asset.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=asset.end_date or today,
                    summary=_('Asset Expiry Reminder'),
                    note=_("The asset '%(name)s' will expire on %(date)s. Please handle the renewal.",
                           name=asset.name, date=asset.end_date or asset.expiry_date),
                    user_id=asset.user_id.id,
                )
            if template and asset.user_id.email:
                template.send_mail(asset.id, force_send=False)
            if client_template and asset.notify_client_on_expiry and asset.partner_id.email:
                client_template.send_mail(asset.id, force_send=False)
            vals = {'state': 'to_renew', 'expiry_notified': True}
            if to_renew_stage:
                vals['stage_id'] = to_renew_stage.id
            asset.write(vals)

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
        """Connect to the asset's URL: uptime + real SSL certificate expiry.
        Escalates risk_level to High when the site is down or the certificate
        expires in under 14 days (never downgrades automatically). An asset
        still in the "New" stage that comes up for the first time is
        considered provisioned and moves to "Running" automatically."""
        today = fields.Date.context_today(self)
        new_stage = self.env.ref('ts_partner_app.stage_new', raise_if_not_found=False)
        running_stage = self.env.ref('ts_partner_app.stage_running', raise_if_not_found=False)
        manager_group = self.env.ref('ts_partner_app.group_partner_asset_manager', raise_if_not_found=False)
        manager_partners = manager_group.user_ids.partner_id if manager_group else self.env['res.partner']
        for asset in self:
            host, port, use_tls = asset._get_health_endpoint()
            if not host:
                continue
            up = False
            ssl_exp = asset.ssl_expiry_date
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
                _logger.info("Health check failed for asset %s (%s): %s", asset.display_name, host, exc)
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
            if alerts and asset.risk_level != 'high':
                vals['risk_level'] = 'high'
                notify_partners = manager_partners | (asset.user_id.partner_id if asset.user_id else self.env['res.partner'])
                asset.message_post(
                    body=_("Health check escalated risk to High: %s.", " and ".join(alerts)),
                    partner_ids=notify_partners.ids,
                )
            provisioned = (up and new_stage and running_stage
                          and asset.stage_id == new_stage)
            if provisioned:
                vals['stage_id'] = running_stage.id
                vals['state'] = 'running'
            asset.write(vals)
            if provisioned:
                asset.message_post(body=_(
                    "Provisioning confirmed — the site is live. Moved from New to Running."))
        return True

    def _cron_check_asset_health(self):
        assets = self.search([
            ('url', '!=', False),
            ('state', '!=', 'closed'),
        ])
        for asset in assets:
            try:
                asset.action_check_health()
            except Exception as exc:  # never let one asset break the cron
                _logger.error("Health check crashed for asset %s: %s", asset.display_name, exc)

    # ------------------------------------------------------------------
    # Weekly digest
    # ------------------------------------------------------------------
    def _cron_send_weekly_digest(self):
        today = fields.Date.context_today(self)
        soon = today + timedelta(days=30)
        stale = today - timedelta(days=60)
        expiring = self.search([('expiry_date', '>=', today), ('expiry_date', '<=', soon),
                                ('state', '!=', 'closed')], order='expiry_date')
        negative = self.search([('gross_margin', '<', 0), ('state', '!=', 'closed')])
        stale_backup = self.search(['&', ('state', '!=', 'closed'),
                                    '|', ('last_backup_check', '=', False),
                                    ('last_backup_check', '<', stale)])
        high_debt = self.search([('technical_debt_level', 'in', ['high', 'critical']),
                                 ('state', '!=', 'closed')])
        down = self.search([('website_up', '=', False), ('last_health_check', '!=', False),
                            ('state', '!=', 'closed')])
        if not (expiring or negative or stale_backup or high_debt or down):
            return

        def _section(title, records, line):
            if not records:
                return ""
            rows = "".join(f"<li>{line(r)}</li>" for r in records[:15])
            more = f"<li>… and {len(records) - 15} more</li>" if len(records) > 15 else ""
            return f"<h3 style='margin:12px 0 4px'>{title} ({len(records)})</h3><ul>{rows}{more}</ul>"

        body = _("<p>Weekly Odoo Clients 360 digest:</p>")
        body += _section(_("Expiring in the next 30 days"), expiring,
                         lambda r: f"{r.name} — {r.partner_id.name} — end date {r.end_date or r.expiry_date}")
        body += _section(_("Sites currently unreachable"), down,
                         lambda r: f"{r.name} — {r.partner_id.name} — last check {r.last_health_check}")
        body += _section(_("Negative gross margin"), negative,
                         lambda r: f"{r.name} — {r.partner_id.name} — margin {r.gross_margin} {r.currency_id.name or ''}")
        body += _section(_("Backup not verified in 60+ days"), stale_backup,
                         lambda r: f"{r.name} — {r.partner_id.name} — last check {r.last_backup_check or 'never'}")
        body += _section(_("High / critical technical debt"), high_debt,
                         lambda r: f"{r.name} — {r.partner_id.name} — {r.technical_debt_level}")

        group = self.env.ref('ts_partner_app.group_partner_asset_manager', raise_if_not_found=False)
        managers = group.user_ids.filtered(lambda u: u.email and u.active) if group else self.env['res.users']
        for manager in managers:
            self.env['mail.mail'].sudo().create({
                'subject': _("Odoo Clients 360 Weekly Digest — %s", today),
                'email_to': manager.email,
                'body_html': body,
                'auto_delete': True,
            }).send()

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self):
        """Aggregate portfolio data for the Odoo Clients 360 OWL dashboard.

        Amounts are summed as-is across records (no currency conversion),
        consistent with the rest of the module (see Financial Overview
        pivot). Fine for single-currency portfolios; multi-currency setups
        should use the pivot/graph view for an accurate breakdown.
        """
        today = fields.Date.context_today(self)
        soon = today + timedelta(days=30)
        stale = today - timedelta(days=60)
        open_domain = [('state', '!=', 'closed')]
        assets = self.search(open_domain)
        currency = self.env.company.currency_id

        mrr = sum(assets.mapped('monthly_billing_client'))
        infra_cost = sum(assets.mapped('infra_monthly_cost'))
        margin = mrr - infra_cost
        margin_pct = (margin / mrr * 100.0) if mrr else 0.0

        type_labels = dict(self._fields['type']._description_selection(self.env))
        by_type = [
            {'type': typ, 'label': type_labels.get(typ, typ or _('Other')), 'count': count}
            for typ, count in self.env['partner.asset']._read_group(
                open_domain, groupby=['type'], aggregates=['__count'])
        ]
        by_type.sort(key=lambda r: r['count'], reverse=True)

        by_stage = [
            {'stage': stage.name if stage else _('No Stage'), 'count': count}
            for stage, count in self.env['partner.asset']._read_group(
                open_domain, groupby=['stage_id'], aggregates=['__count'])
        ]

        expiring = assets.filtered(
            lambda a: a.expiry_date and today <= a.expiry_date <= soon).sorted('expiry_date')
        down = assets.filtered(lambda a: a.last_health_check and not a.website_up)
        backup_stale = assets.filtered(
            lambda a: not a.last_backup_check or a.last_backup_check < stale)
        high_risk = assets.filtered(lambda a: a.risk_level == 'high')
        negative_margin = assets.filtered(lambda a: a.gross_margin < 0).sorted('gross_margin')

        Infra = self.env['partner.infrastructure']
        hosting_labels = dict(Infra._fields['hosting_type']._description_selection(self.env))
        by_hosting_type = [
            {'hosting_type': typ, 'label': hosting_labels.get(typ, typ), 'count': count}
            for typ, count in Infra._read_group([], groupby=['hosting_type'], aggregates=['__count'])
        ]
        by_hosting_type.sort(key=lambda r: r['count'], reverse=True)
        covered_partner_ids = set(Infra.search([]).partner_id.ids)
        missing_infra_partner_ids = [pid for pid in assets.partner_id.ids if pid not in covered_partner_ids]

        client_app_tag = self.env.ref('ts_partner_app.project_tag_client_app', raise_if_not_found=False)
        client_projects = self.env['project.project'].search([
            ('tag_ids', 'in', client_app_tag.id if client_app_tag else 0),
        ])
        project_tasks = self.env['project.task'].search([('project_id', 'in', client_projects.ids)])
        open_project_tasks = project_tasks.filtered(lambda t: not t.stage_id.fold)
        project_by_stage = [
            {'stage_id': stage.id, 'label': stage.name, 'count': count}
            for stage, count in self.env['project.task']._read_group(
                [('project_id', 'in', client_projects.ids)], groupby=['stage_id'], aggregates=['__count'])
            if stage
        ]
        project_by_stage.sort(key=lambda r: r['count'], reverse=True)

        def _asset_row(a, extra=None):
            row = {'id': a.id, 'name': a.name, 'partner': a.partner_id.display_name}
            row.update(extra or {})
            return row

        return {
            'currency_symbol': currency.symbol,
            'currency_position': currency.position,
            'kpi': {
                'client_count': len(assets.partner_id),
                'asset_count': len(assets),
                'mrr': mrr,
                'infra_cost': infra_cost,
                'margin': margin,
                'margin_pct': margin_pct,
            },
            'by_type': by_type,
            'by_stage': by_stage,
            'risk': {
                'high_risk_count': len(high_risk),
                'down_count': len(down),
                'backup_stale_count': len(backup_stale),
                'negative_margin_count': len(negative_margin),
            },
            'expiring_soon': [
                _asset_row(a, {'type': type_labels.get(a.type, a.type),
                               'expiry_date': fields.Date.to_string(a.expiry_date)})
                for a in expiring[:8]
            ],
            'down_assets': [
                _asset_row(a, {'last_health_check': fields.Datetime.to_string(a.last_health_check)})
                for a in down[:8]
            ],
            'negative_margin_assets': [
                _asset_row(a, {'margin': a.gross_margin}) for a in negative_margin[:8]
            ],
            'infrastructure': {
                'by_hosting_type': by_hosting_type,
                'missing_count': len(missing_infra_partner_ids),
                'missing_partner_ids': missing_infra_partner_ids,
            },
            'projects': {
                'project_count': len(client_projects),
                'open_task_count': len(open_project_tasks),
                'project_ids': client_projects.ids,
                'by_stage': project_by_stage,
            },
        }

    # ------------------------------------------------------------------
    # Portal
    # ------------------------------------------------------------------
    def _portal_request_renewal(self, message=None):
        """Called (sudo) from the portal controller when a client requests a renewal."""
        self.ensure_one()
        body = _("The customer requested a renewal of this asset via the portal.")
        if message:
            body += _(" Message: %s", message)
        self.message_post(body=body)
        if self.user_id:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=fields.Date.context_today(self),
                summary=_('Portal renewal request'),
                note=body,
                user_id=self.user_id.id,
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_create_renewal_order(self):
        self.ensure_one()
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'asset_id': self.id,
        })
        product = self.env.ref('ts_partner_app.product_asset_renewal', raise_if_not_found=False)
        if product:
            type_label = dict(self._fields['type']._description_selection(self.env)).get(self.type, self.type)
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': product.id,
                'name': _("Renewal: %(name)s (%(type)s)", name=self.name, type=type_label),
                'product_uom_qty': 1,
                'price_unit': self.monthly_billing_client or 0.0,
            })
        self.write({'sale_order_id': order.id})
        self.message_post(body=_("Renewal quotation %(order)s created.", order=order.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_invoice(self):
        """One-off billing (project completed, ad-hoc maintenance) — as opposed to
        action_create_renewal_order, which is specifically the recurring-subscription
        renewal quote. Creates a draft Sale Order with a blank-priced line; the amount
        is deliberately left for the user to fill in rather than guessed from
        monthly_billing_client, since these are one-time amounts that vary per job."""
        self.ensure_one()
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'asset_id': self.id,
        })
        product = self.env.ref('ts_partner_app.product_client_services', raise_if_not_found=False)
        if product:
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': product.id,
                'name': _("Services: %s", self.name),
                'product_uom_qty': 1,
                'price_unit': 0.0,
            })
        self.message_post(body=_("Invoice quotation %(order)s created.", order=order.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_tasks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tasks'),
            'res_model': 'project.task',
            'view_mode': 'list,form,kanban',
            'domain': [('asset_id', '=', self.id)],
            'context': {'default_asset_id': self.id, 'default_partner_id': self.partner_id.id},
        }

    def action_open_client_project(self):
        self.ensure_one()
        return self.client_project_id.action_view_tasks()

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
        }

    def _get_or_create_client_project(self):
        """Find-or-create a dedicated project for this asset's client (as opposed to
        the shared "Client Tasks" project behind Create Task, meant for one-off
        follow-ups) — for a real multi-task engagement: onboarding, migration,
        a support contract, etc."""
        self.ensure_one()
        partner = self.partner_id
        shared_project = self.env.ref('ts_partner_app.project_client_tasks', raise_if_not_found=False)
        project = self.env['project.project'].search([
            ('partner_id', '=', partner.id),
            ('id', '!=', shared_project.id if shared_project else 0),
        ], limit=1)
        if not project:
            client_app_tag = self.env.ref('ts_partner_app.project_tag_client_app', raise_if_not_found=False)
            project = self.env['project.project'].create({
                'name': partner.name,
                'partner_id': partner.id,
                'tag_ids': [(4, client_app_tag.id)] if client_app_tag else False,
            })
            stage_xmlids = ['project_task_stage_todo', 'project_task_stage_in_progress',
                           'project_task_stage_waiting_client', 'project_task_stage_done']
            stages = self.env['project.task.type']
            for xmlid in stage_xmlids:
                stage = self.env.ref(f'ts_partner_app.{xmlid}', raise_if_not_found=False)
                if stage:
                    stages |= stage
            stages.write({'project_ids': [(4, project.id)]})
            self.message_post(body=_("New client project created: %s", project.name))
        return project

    def action_create_client_project(self):
        """Open the New Client Project wizard so implementation tasks and modules can
        be picked from the template catalog before creating (or adding to) this
        client's dedicated project. The wizard record (and its template lines) is
        created here, server-side, rather than left to default_get — so the dialog
        opens on an already-persisted record instead of an unsaved/virtual one."""
        self.ensure_one()
        wizard = self.env['partner.project.template.wizard'].create({'asset_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'partner.project.template.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create_sale_offer(self):
        """Open the Create Sale Offer wizard — pick from the service products created by
        Configuration > Import Products and generate a real quotation, the same pattern
        as the New Client Project wizard but for Sales instead of project tasks."""
        self.ensure_one()
        wizard = self.env['partner.sale.offer.wizard'].create({'asset_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'partner.sale.offer.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_infrastructure(self):
        self.ensure_one()
        return self.partner_id.action_view_infrastructure()

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
        return {
            'type': 'ir.actions.act_url',
            'url': self.url,
            'target': 'new',
        }

    def action_open_url2(self):
        self.ensure_one()
        if not self.url2:
            return
        return {
            'type': 'ir.actions.act_url',
            'url': self.url2,
            'target': 'new',
        }
