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

    # URLs, logins, passwords and live health monitoring live on the client's
    # Odoo environments (partner.environment), not on the asset.

    subscription_number = fields.Char(string='Subscription Number', tracking=True)
    show_subscription_number = fields.Boolean(string='Show Subscription Number', default=False, copy=False)
    start_date = fields.Date(string='Subscription Start Date', tracking=True)
    subscription_term = fields.Selection([
        ('1m', '1 Month'),
        ('1y', '1 Year'),
        ('3y', '3 Years'),
        ('5y', '5 Years'),
        ('custom', 'Custom'),
    ], string='Subscription Term', default='1y', tracking=True,
        help="Auto-fills the Subscription End Date from the Start Date. Choose "
             "'Custom' to set the End Date by hand.")
    end_date = fields.Date(
        string='Subscription End Date', tracking=True,
        compute='_compute_end_date', store=True, readonly=False,
        help="Auto-filled from Start Date + Subscription Term. Set the term to "
             "'Custom' to enter it by hand; a manual value is kept until the "
             "Start Date or the term changes.")
    project_start_date = fields.Date(
        string='Project Start Date', tracking=True,
        help="Start of the project engagement. Can differ from the Odoo "
             "subscription dates and does not drive expiry reminders or renewals.")
    project_end_date = fields.Date(
        string='Project End Date', tracking=True,
        help="End of the project engagement. Can differ from the Odoo "
             "subscription dates and does not drive expiry reminders or renewals.")
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
    license_currency_id = fields.Many2one(
        'res.currency', string='License Currency',
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False) or self.env.company.currency_id,
        help="Currency Odoo bills the user licenses in — usually USD or EUR, "
             "regardless of the currency used elsewhere on this asset.")
    license_cost = fields.Monetary(string='Annual License Cost / User', currency_field='license_currency_id', tracking=True,
                                   help="List price of one user license per YEAR, in the License Currency. "
                                        "Odoo Enterprise licenses are billed annually per user; this is "
                                        "multiplied by Licenses and divided by 12 for the monthly breakdown.")
    license_cost_billed = fields.Boolean(
        string='Billed by Us', default=False, tracking=True,
        help="Included in Gross Margin only if checked. Leave unchecked when the client pays "
             "Odoo directly for licenses, which is the common case.")
    license_cost_total = fields.Monetary(string='Annual License Cost (Total)', compute='_compute_license_cost_total',
                                         currency_field='license_currency_id', store=True,
                                         help="Annual License Cost / User x Licenses, in the License Currency.")
    license_cost_total_local = fields.Monetary(string='Annual License Cost (Local)', compute='_compute_license_cost_total',
                                               currency_field='currency_id', store=True,
                                               help="Annual license total converted to this asset's currency "
                                                    "at the current exchange rate.")
    license_monthly_cost_currency = fields.Monetary(
        string='Monthly License Cost (License Currency)', compute='_compute_license_cost_total',
        currency_field='license_currency_id', store=True,
        help="Annual License Cost (Total) / 12, in the License Currency - the monthly "
             "figure before conversion to the local currency.")
    license_monthly_cost = fields.Monetary(string='Monthly License Cost (Local)', compute='_compute_license_cost_total',
                                           currency_field='currency_id', store=True,
                                           help="Annual License Cost (Local) / 12 - the figure that feeds the "
                                                "monthly cost breakdown and Gross Margin.")
    license_currency_rate_missing = fields.Boolean(
        string='License FX Rate Missing', compute='_compute_license_currency_rate_missing',
        help="The License Currency differs from this asset's currency but no exchange "
             "rate is configured, so the converted figures fall back to 1:1. Set up "
             "Automatic Currency Rates in Configuration > Settings.")
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

    # Backup, risk and live health monitoring (SSL / uptime) are tracked per
    # Odoo environment. This mirror of the primary environment's risk level is
    # kept for the kanban / list decorations and dashboard filters.
    risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Risk Level', compute='_compute_risk_level', store=True, tracking=True,
        help="Highest risk level across this asset's Odoo environments (or the "
             "primary one). Set it on the environment.")

    license_count = fields.Integer(string='Licenses', tracking=True,
                                   help="Number of user licenses / seats this client is on.")

    # Odoo environments — version, modules, logins, health and repositories
    # live on partner.environment (prod / staging / ...), not on the asset.
    environment_ids = fields.One2many('partner.environment', 'asset_id', string='Environments')
    environment_count = fields.Integer(string='Environments', compute='_compute_environment_count')
    primary_environment_id = fields.Many2one('partner.environment', string='Primary Environment',
                                             compute='_compute_primary_environment')

    # Project integration
    has_project = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Has Project?', required=True,
        compute='_compute_has_project', store=True, readonly=False, tracking=True,
        help="Whether this client engagement includes a project. Set to 'No' when "
             "there is no project — the Project link and Project Start / End Date "
             "fields are then hidden.")
    project_id = fields.Many2one(
        'project.project', string='Project', tracking=True,
        help="Existing project linked to this client asset. When set, the "
             "'Client Project' stat button and 'Open Project' use it instead of "
             "auto-discovering a project by customer.")
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

    # Actuals - real revenue / cost from Accounting vs the estimate above
    actual_move_ids = fields.One2many('account.move', 'asset_id', string='Linked Invoices & Bills')
    actuals_period = fields.Selection([
        ('this_year', 'This Year'),
        ('trailing_12m', 'Trailing 12 Months'),
        ('since_start', 'Since Start Date'),
        ('custom', 'Custom'),
    ], string='Actuals Period', default='trailing_12m', required=True)
    actuals_date_from = fields.Date(
        string='Actuals From', compute='_compute_actuals_dates', store=True, readonly=False)
    actuals_date_to = fields.Date(
        string='Actuals To', compute='_compute_actuals_dates', store=True, readonly=False)
    actual_revenue = fields.Monetary(string='Actual Revenue (untaxed)', compute='_compute_actuals',
                                     currency_field='currency_id',
                                     help="Posted customer invoices minus credit notes tagged to this "
                                          "asset, within the Actuals Period. Untaxed amount.")
    actual_revenue_total = fields.Monetary(string='Actual Revenue (with tax)', compute='_compute_actuals',
                                           currency_field='currency_id',
                                           help="Same as Actual Revenue but the full invoiced amount, tax included.")
    actual_cost = fields.Monetary(string='Actual Cost (untaxed)', compute='_compute_actuals',
                                  currency_field='currency_id',
                                  help="Posted vendor bills minus refunds tagged to this asset, "
                                       "within the Actuals Period. Untaxed amount.")
    actual_cost_total = fields.Monetary(string='Actual Cost (with tax)', compute='_compute_actuals',
                                        currency_field='currency_id')
    actual_margin = fields.Monetary(string='Actual Margin (untaxed)', compute='_compute_actuals',
                                    currency_field='currency_id')
    actual_margin_total = fields.Monetary(string='Actual Margin (with tax)', compute='_compute_actuals',
                                          currency_field='currency_id')
    actual_move_count = fields.Integer(string='Linked Move Count', compute='_compute_actuals')

    # ------------------------------------------------------------------
    # Encryption helpers
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

    @api.depends('project_id')
    def _compute_has_project(self):
        """Default the radio from whether a project is linked. Once a value is
        stored it is kept (readonly=False), so linking then unlinking a project
        does not silently flip the user's explicit choice back."""
        for record in self:
            if record.project_id:
                record.has_project = 'yes'
            elif not record.has_project:
                record.has_project = 'no'

    @api.onchange('has_project')
    def _onchange_has_project(self):
        """Clear the project fields when the engagement has no project."""
        if self.has_project == 'no':
            self.project_id = False
            self.project_start_date = False
            self.project_end_date = False

    @api.onchange('project_id')
    def _onchange_project_id(self):
        """Propose the project engagement dates from the linked project. Only
        fills blanks — a value already entered by hand is kept."""
        project = self.project_id
        if project:
            self.has_project = 'yes'
        if not project:
            return
        if not self.project_start_date and project.date_start:
            self.project_start_date = project.date_start
        if not self.project_end_date and project.date:
            self.project_end_date = project.date

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('stage_id')
    def _compute_color(self):
        for record in self:
            record.color = record.stage_id.color

    @api.depends('license_cost', 'license_count', 'license_currency_id', 'currency_id', 'company_id')
    def _compute_license_cost_total(self):
        today = fields.Date.context_today(self)
        for record in self:
            annual = record.license_cost * record.license_count
            record.license_cost_total = annual
            record.license_monthly_cost_currency = annual / 12.0
            license_currency = record.license_currency_id or record.currency_id
            if license_currency and record.currency_id and license_currency != record.currency_id:
                annual_local = license_currency._convert(
                    annual, record.currency_id,
                    record.company_id or self.env.company, today)
            else:
                annual_local = annual
            record.license_cost_total_local = annual_local
            record.license_monthly_cost = annual_local / 12.0

    @api.depends('license_currency_id', 'currency_id', 'company_id')
    def _compute_license_currency_rate_missing(self):
        today = fields.Date.context_today(self)
        Currency = self.env['res.currency']
        for record in self:
            missing = False
            license_currency = record.license_currency_id
            if license_currency and record.currency_id and license_currency != record.currency_id:
                company = record.company_id or self.env.company
                try:
                    rate = Currency._get_conversion_rate(
                        license_currency, record.currency_id, company, today)
                except Exception:
                    rate = 1.0
                missing = abs(rate - 1.0) < 1e-6
            record.license_currency_rate_missing = missing

    @api.depends('server_cost', 'server_cost_billed',
                'license_monthly_cost', 'license_cost_billed',
                'backup_cost', 'backup_cost_billed',
                'maintenance_cost', 'maintenance_cost_billed',
                'external_services_cost', 'external_services_cost_billed')
    def _compute_infra_monthly_cost(self):
        for record in self:
            record.infra_monthly_cost = (
                (record.server_cost if record.server_cost_billed else 0)
                + (record.license_monthly_cost if record.license_cost_billed else 0)
                + (record.backup_cost if record.backup_cost_billed else 0)
                + (record.maintenance_cost if record.maintenance_cost_billed else 0)
                + (record.external_services_cost if record.external_services_cost_billed else 0)
            )

    @api.depends('partner_id.infrastructure_id')
    def _compute_partner_infrastructure(self):
        for record in self:
            record.partner_infrastructure_count = len(record.partner_id.infrastructure_id)

    @api.depends('environment_ids')
    def _compute_environment_count(self):
        for record in self:
            record.environment_count = len(record.environment_ids)

    @api.depends('environment_ids.is_primary', 'environment_ids.current_version')
    def _compute_primary_environment(self):
        for record in self:
            envs = record.environment_ids
            record.primary_environment_id = (
                envs.filtered('is_primary')[:1]
                or envs.filtered('current_version')[:1]
                or envs[:1]
            )

    @api.depends('infra_monthly_cost', 'monthly_billing_client')
    def _compute_gross_margin(self):
        for record in self:
            record.gross_margin = record.monthly_billing_client - record.infra_monthly_cost
            record.margin_pct = (record.gross_margin / record.monthly_billing_client * 100.0
                                 ) if record.monthly_billing_client else 0.0

    _SUBSCRIPTION_TERM_DELTAS = {
        '1m': relativedelta(months=1),
        '1y': relativedelta(years=1),
        '3y': relativedelta(years=3),
        '5y': relativedelta(years=5),
    }

    @api.depends('start_date', 'subscription_term')
    def _compute_end_date(self):
        for record in self:
            delta = self._SUBSCRIPTION_TERM_DELTAS.get(record.subscription_term)
            if delta and record.start_date:
                record.end_date = record.start_date + delta
            else:
                # 'Custom' (or no term / no start date): keep the current value,
                # including one entered by hand.
                record.end_date = record.end_date

    @api.depends('end_date', 'reminder_days')
    def _compute_expiry_date(self):
        for record in self:
            if record.end_date:
                record.expiry_date = record.end_date - timedelta(days=record.reminder_days or 60)
            else:
                record.expiry_date = False

    @api.depends('environment_ids.risk_level')
    def _compute_risk_level(self):
        order = {'low': 0, 'medium': 1, 'high': 2}
        for record in self:
            levels = [e.risk_level for e in record.environment_ids if e.risk_level]
            if levels:
                record.risk_level = max(levels, key=lambda l: order.get(l, 0))
            else:
                record.risk_level = 'low'

    def _compute_task_count(self):
        counts = {
            asset.id: count
            for asset, count in self.env['project.task']._read_group(
                [('asset_id', 'in', self.ids)], groupby=['asset_id'], aggregates=['__count'])
        }
        for record in self:
            record.task_count = counts.get(record.id, 0)

    @api.depends('project_id', 'partner_id')
    def _compute_client_project(self):
        client_app_tag = self.env.ref('ts_partner_app.project_tag_client_app', raise_if_not_found=False)
        # Assets without an explicit project fall back to auto-discovery by customer.
        auto_assets = self.filtered(lambda r: not r.project_id)
        partner_ids = auto_assets.mapped('partner_id').ids
        projects = self.env['project.project'].search([
            ('partner_id', 'in', partner_ids),
            ('tag_ids', 'in', client_app_tag.id if client_app_tag else 0),
        ]) if partner_ids else self.env['project.project']
        project_by_partner = {project.partner_id.id: project for project in projects}
        effective_project_ids = (projects | self.mapped('project_id')).ids
        task_counts = {
            project.id: count
            for project, count in self.env['project.task']._read_group(
                [('project_id', 'in', effective_project_ids)], groupby=['project_id'], aggregates=['__count'])
        } if effective_project_ids else {}
        for record in self:
            project = record.project_id or project_by_partner.get(record.partner_id.id)
            record.client_project_id = project.id if project else False
            record.client_project_task_count = task_counts.get(project.id, 0) if project else 0

    def _compute_invoices(self):
        orders = self.env['sale.order'].search([('asset_id', 'in', self.ids)])
        invoices_by_asset = {}
        for order in orders:
            invoices_by_asset.setdefault(order.asset_id.id, self.env['account.move'])
            invoices_by_asset[order.asset_id.id] |= order.invoice_ids
        tagged = self.env['account.move'].search([('asset_id', 'in', self.ids)])
        for move in tagged:
            invoices_by_asset.setdefault(move.asset_id.id, self.env['account.move'])
            invoices_by_asset[move.asset_id.id] |= move
        for record in self:
            invoices = invoices_by_asset.get(record.id, self.env['account.move'])
            record.invoice_ids = invoices
            record.invoice_count = len(invoices)

    @api.depends('actuals_period', 'start_date')
    def _compute_actuals_dates(self):
        today = fields.Date.context_today(self)
        for record in self:
            period = record.actuals_period
            if period == 'this_year':
                record.actuals_date_from = today.replace(month=1, day=1)
                record.actuals_date_to = today
            elif period == 'trailing_12m':
                record.actuals_date_from = today - relativedelta(months=12)
                record.actuals_date_to = today
            elif period == 'since_start':
                record.actuals_date_from = record.start_date or (today - relativedelta(months=12))
                record.actuals_date_to = today
            else:  # 'custom' - keep whatever is set (entered by hand)
                record.actuals_date_from = record.actuals_date_from
                record.actuals_date_to = record.actuals_date_to

    @api.depends('actual_move_ids.state', 'actual_move_ids.amount_untaxed',
                 'actual_move_ids.amount_total', 'actual_move_ids.move_type',
                 'actual_move_ids.invoice_date',
                 'actuals_date_from', 'actuals_date_to', 'currency_id')
    def _compute_actuals(self):
        AccountMove = self.env['account.move']
        for record in self:
            if not record.id:
                record.actual_revenue = record.actual_revenue_total = 0.0
                record.actual_cost = record.actual_cost_total = 0.0
                record.actual_margin = record.actual_margin_total = 0.0
                record.actual_move_count = 0
                continue
            company = record.company_id or self.env.company
            totals = AccountMove._ts_actuals_totals(
                [('asset_id', '=', record.id)],
                record.actuals_date_from, record.actuals_date_to,
                company, record.currency_id)
            record.actual_revenue = totals['revenue_untaxed']
            record.actual_revenue_total = totals['revenue_total']
            record.actual_cost = totals['cost_untaxed']
            record.actual_cost_total = totals['cost_total']
            record.actual_margin = totals['revenue_untaxed'] - totals['cost_untaxed']
            record.actual_margin_total = totals['revenue_total'] - totals['cost_total']
            record.actual_move_count = totals['count']

    def action_view_actual_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices & Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {
                'default_asset_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
        }

    def action_link_moves(self):
        """Open all of this client's invoices and bills so they can be tagged to
        the asset (the list is editable and pre-fills Client Asset)."""
        self.ensure_one()
        partner_ids = (self.partner_id | self.partner_id.child_ids).ids or [self.partner_id.id]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Link Invoices & Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')),
                '|', ('partner_id', 'in', partner_ids), ('asset_id', '=', self.id),
            ],
            'context': {'default_asset_id': self.id},
        }

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
        if (vals.keys() & {'end_date', 'expiry_date', 'start_date', 'subscription_term'}
                and 'expiry_notified' not in vals):
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
    # Live health checks (SSL / uptime) — now run per Odoo environment.
    # ------------------------------------------------------------------
    def _cron_check_asset_health(self):
        """Kept for the existing scheduled action; delegates to the
        per-environment health check."""
        self.env['partner.environment']._cron_check_environment_health()

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
        Environment = self.env['partner.environment']
        open_env = lambda e: not e.asset_id or e.asset_id.state != 'closed'
        stale_backup = Environment.search([
            '|', ('last_backup_check', '=', False), ('last_backup_check', '<', stale),
        ]).filtered(open_env)
        high_debt = Environment.search([
            ('technical_debt_level', 'in', ['high', 'critical']),
        ]).filtered(open_env)
        down = Environment.search([
            ('website_up', '=', False), ('last_health_check', '!=', False),
        ]).filtered(open_env)
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
                         lambda r: f"{r.partner_id.name} / {r.name} — last check {r.last_health_check}")
        body += _section(_("Negative gross margin"), negative,
                         lambda r: f"{r.name} — {r.partner_id.name} — margin {r.gross_margin} {r.currency_id.name or ''}")
        body += _section(_("Backup not verified in 60+ days"), stale_backup,
                         lambda r: f"{r.partner_id.name} / {r.name} — last check {r.last_backup_check or 'never'}")
        body += _section(_("High / critical technical debt"), high_debt,
                         lambda r: f"{r.partner_id.name} / {r.name} — {r.technical_debt_level}")

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
        Environment = self.env['partner.environment']
        env_open = lambda e: not e.asset_id or e.asset_id.state != 'closed'
        down = Environment.search([
            ('last_health_check', '!=', False), ('website_up', '=', False),
        ]).filtered(env_open)
        backup_stale = Environment.search([
            '|', ('last_backup_check', '=', False), ('last_backup_check', '<', stale),
        ]).filtered(env_open)
        high_risk = assets.filtered(lambda a: a.risk_level == 'high')
        negative_margin = assets.filtered(lambda a: a.gross_margin < 0).sorted('gross_margin')
        upgrades_due = Environment.search([
            ('upgrade_available', '=', True),
        ]).filtered(env_open).sorted(lambda e: e.current_version.sequence)

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
                'upgrades_due_count': len(upgrades_due),
                'upgrades_due_ids': upgrades_due.ids,
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

    def action_link_existing_tasks(self):
        """Open the wizard to attach existing project tasks to this asset."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Link Existing Tasks'),
            'res_model': 'partner.asset.task.link.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_asset_id': self.id},
        }

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
        if self.project_id:
            return self.project_id
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

    def action_view_environments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Environments"),
            'res_model': 'partner.environment',
            'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {
                'default_asset_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
        }

    def toggle_subscription_number(self):
        self.ensure_one()
        self.show_subscription_number = not self.show_subscription_number
