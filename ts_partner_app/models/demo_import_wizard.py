# ----------------------------------------------------------------------
# TEMPORARY DEMO/DEV HELPER
# ----------------------------------------------------------------------
# Lets a manager populate the database with a handful of realistic demo
# clients and assets from Configuration > Import Demo, purely so the
# module's behaviour (dashboard, expiry engine, financial overview...)
# can be seen without manual data entry.
#
# This is scaffolding, not a feature: it is meant to be removed later.
# To dismiss it, delete this file, its view (views/demo_import_wizard_
# views.xml), the menu item in views/partner_asset_views.xml, and the
# corresponding lines in __manifest__.py / models/__init__.py /
# security/ir.model.access.csv.
# ----------------------------------------------------------------------
from dateutil.relativedelta import relativedelta

from odoo import models, fields, _
from odoo.exceptions import UserError


class TsPartnerAppDemoImportWizard(models.TransientModel):
    _name = 'ts.partner.app.demo.import.wizard'
    _description = 'Odoo Clients 360: Import Demo Data (temporary dev helper)'

    def _default_info(self):
        return _(
            "<p>This creates 4 demo clients exercising every part of the app: "
            "domains, hosting, SSL and server assets in every stage/risk level, "
            "credentials, custom &amp; native modules, tags, a campaign link, a "
            "linked (draft) renewal quote, infrastructure profiles with "
            "credentials, technical contacts, and client projects with tasks in "
            "every stage — some expiring soon, some overdue, one with negative "
            "margin, one client email notification turned off on purpose.</p>"
            "<p>Running it again will not duplicate data — use "
            "<b>Remove Demo Data</b> first if you want a clean slate.</p>"
        )

    info = fields.Html(default=_default_info, readonly=True, sanitize=False,
                       help="Explanatory text only.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _xmlid(self, name):
        return 'ts_partner_app.%s' % name

    def _ensure_record(self, xmlid_name, model, vals):
        """Create-or-fetch a record registered under a demo_* xmlid, so a
        second run of the wizard updates in place instead of duplicating,
        and Remove Demo Data can find everything it created.

        All vals here are hardcoded English literals. Forced to lang='en_US' so
        a write on re-import always lands in the English slot of a translatable
        field instead of the current user's session language (e.g. bs_BA),
        which would otherwise silently clobber a real Bosnian translation with
        that literal English text."""
        full_xmlid = self._xmlid(xmlid_name)
        env_en = self.env(context={**self.env.context, 'lang': 'en_US'})
        record = env_en.ref(full_xmlid, raise_if_not_found=False)
        if record and record.exists():
            record.write(vals)
            return record
        record = env_en[model].create(vals)
        env_en['ir.model.data'].create({
            'name': xmlid_name,
            'module': 'ts_partner_app',
            'model': model,
            'res_id': record.id,
            'noupdate': True,
        })
        return record

    def _ref(self, xmlid):
        """Reference an existing catalog record (tags, native apps) shipped by
        the module's own static data files — not demo-tracked, just reused."""
        return self.env.ref(self._xmlid(xmlid), raise_if_not_found=False)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def action_import_demo_data(self):
        self.ensure_one()
        today = fields.Date.context_today(self)

        tag_critical = self._ensure_record('demo_tag_vip', 'partner.asset.tag', {
            'name': 'VIP Client', 'color': 1,
        })
        tag_trial = self._ensure_record('demo_tag_trial', 'partner.asset.tag', {
            'name': 'Trial', 'color': 4,
        })
        # Reuse a few tags from the module's own static catalog for variety,
        # instead of only ever using the two demo-only tags above.
        tag_go_live = self._ref('tag_go_live')
        tag_support = self._ref('tag_support')
        tag_saas = self._ref('tag_saas')
        tag_on_premise = self._ref('tag_on_premise')
        tag_integration = self._ref('tag_integration')
        tag_migration = self._ref('tag_migration')

        stage_new = self.env.ref(self._xmlid('stage_new'), raise_if_not_found=False)
        stage_running = self.env.ref(self._xmlid('stage_running'), raise_if_not_found=False)
        stage_to_renew = self.env.ref(self._xmlid('stage_to_renew'), raise_if_not_found=False)

        partners = {
            'acme': self._ensure_record('demo_partner_acme', 'res.partner', {
                'name': 'Acme Retail Group', 'is_company': True,
                'email': 'contact@acme-retail.example', 'city': 'Sarajevo', 'phone': '+387 33 100 200',
            }),
            'nordic': self._ensure_record('demo_partner_nordic', 'res.partner', {
                'name': 'Nordic Tech Solutions', 'is_company': True,
                'email': 'hello@nordictech.example', 'city': 'Oslo', 'phone': '+47 22 00 11 22',
            }),
            'blueharbor': self._ensure_record('demo_partner_blueharbor', 'res.partner', {
                'name': 'Blue Harbor Logistics', 'is_company': True,
                'email': 'it@blueharbor.example', 'city': 'Rotterdam', 'phone': '+31 10 200 3000',
            }),
            'sunrise': self._ensure_record('demo_partner_sunrise', 'res.partner', {
                'name': 'Sunrise Media Agency', 'is_company': True,
                'email': 'office@sunrisemedia.example', 'city': 'Zagreb', 'phone': '+385 1 555 6677',
            }),
        }

        # One IT contact per client, as a child of the company — exercises the
        # Client IT contact / Decision maker / Emergency contact fields' domain
        # restriction (contacts must belong to the asset's own client).
        contacts = {
            'acme': self._ensure_record('demo_contact_acme_it', 'res.partner', {
                'name': 'Amira Hodžić', 'parent_id': partners['acme'].id,
                'function': 'IT Manager', 'email': 'amira@acme-retail.example', 'phone': '+387 33 100 201',
            }),
            'nordic': self._ensure_record('demo_contact_nordic_it', 'res.partner', {
                'name': 'Lars Eriksen', 'parent_id': partners['nordic'].id,
                'function': 'CTO', 'email': 'lars@nordictech.example', 'phone': '+47 22 00 11 23',
            }),
            'blueharbor': self._ensure_record('demo_contact_blueharbor_it', 'res.partner', {
                'name': 'Sven de Groot', 'parent_id': partners['blueharbor'].id,
                'function': 'Operations Manager', 'email': 'sven@blueharbor.example', 'phone': '+31 10 200 3001',
            }),
            'sunrise': self._ensure_record('demo_contact_sunrise_it', 'res.partner', {
                'name': 'Petra Novak', 'parent_id': partners['sunrise'].id,
                'function': 'Founder', 'email': 'petra@sunrisemedia.example', 'phone': '+385 1 555 6678',
            }),
        }

        # A couple of UTM campaigns, so campaign_id has something realistic to link to.
        campaign_referral = self._ensure_record('demo_campaign_referral', 'utm.campaign', {
            'name': 'Partner Referral Program',
        })
        campaign_ads = self._ensure_record('demo_campaign_ads', 'utm.campaign', {
            'name': 'Google Ads — SMB',
        })

        def d(days=0, months=0):
            return today + relativedelta(days=days, months=months)

        native = {name: self._ref('native_module_%s' % name) for name in (
            'sales', 'crm', 'accounting', 'invoicing', 'inventory', 'purchase',
            'website', 'ecommerce', 'project', 'helpdesk',
        )}

        def native_ids(*names):
            recs = self.env['partner.asset.native.module']
            for name in names:
                rec = native.get(name)
                if rec:
                    recs |= rec
            return [(6, 0, recs.ids)]

        # Acme — healthy domain, an Odoo.sh expiring soon, VIP tag.
        self._ensure_record('demo_asset_acme_domain', 'partner.asset', {
            'name': 'acme-retail.com', 'partner_id': partners['acme'].id, 'type': 'online',
            'url': 'https://acme-retail.example',
            'login_email': 'admin@acme-retail.example', 'password': 'Demo-Pass-2026!',
            'start_date': d(months=-11), 'end_date': d(months=1),
            'reminder_days': 60, 'renewal_period': 12,
            'server_cost': 0, 'monthly_billing_client': 15,
            'stage_id': stage_running.id if stage_running else False,
            'state': 'running', 'risk_level': 'low',
            'tag_ids': [(6, 0, (tag_critical | tag_go_live).ids)],
            'campaign_id': campaign_referral.id,
            'native_module_ids': native_ids('sales', 'crm', 'accounting', 'website'),
            'client_it_contact': contacts['acme'].id,
            'decision_maker_contact': partners['acme'].id,
            'emergency_contact': contacts['acme'].id,
            'website_up': True, 'last_health_check': fields.Datetime.now(),
            'ssl_expiry_date': d(months=1),
        })

        acme_sh = self._ensure_record('demo_asset_acme_odoo_sh', 'partner.asset', {
            'name': 'Acme Production — Odoo.sh', 'partner_id': partners['acme'].id, 'type': 'odoo_sh',
            'url': 'https://acme-prod.odoo.com',
            'subscription_number': 'SUB-ACME-2026-118',
            'start_date': d(months=-6), 'end_date': d(days=10),
            'reminder_days': 60, 'renewal_period': 12,
            'server_cost': 120, 'license_cost': 20, 'license_count': 4, 'backup_cost': 15,
            'monthly_billing_client': 350,
            'stage_id': stage_to_renew.id if stage_to_renew else False,
            'state': 'to_renew', 'risk_level': 'medium',
            'current_version': '18.0', 'latest_version': '19.0',
            'technical_debt_level': 'medium',
            'backup_verified': True, 'dr_plan_documented': True,
            'tag_ids': [(6, 0, (tag_critical | tag_migration).ids)],
            'native_module_ids': native_ids('sales', 'purchase', 'inventory', 'accounting', 'invoicing', 'project'),
        })

        self._ensure_record('demo_asset_acme_ssl', 'partner.asset', {
            'name': 'acme-retail.com — SSL', 'partner_id': partners['acme'].id, 'type': 'online',
            'url': 'https://acme-retail.example',
            'start_date': d(months=-11), 'end_date': d(days=5),
            'reminder_days': 14, 'renewal_period': 12,
            'monthly_billing_client': 0,
            'stage_id': stage_to_renew.id if stage_to_renew else False,
            'state': 'to_renew', 'risk_level': 'high',
            'website_up': False, 'last_health_check': fields.Datetime.now(),
            'ssl_expiry_date': d(days=5),
            'backup_verified': False, 'dr_plan_documented': False,
        })

        # Nordic — overdue hosting (expired), git repo.
        nordic_hosting = self._ensure_record('demo_asset_nordic_hosting', 'partner.asset', {
            'name': 'Nordic VPS Hosting', 'partner_id': partners['nordic'].id, 'type': 'online',
            'url': 'https://vps.nordictech.example',
            'start_date': d(months=-13), 'end_date': d(days=-5),
            'reminder_days': 60, 'renewal_period': 12,
            'server_cost': 60, 'backup_cost': 10,
            'monthly_billing_client': 90,
            'stage_id': stage_to_renew.id if stage_to_renew else False,
            'state': 'to_renew', 'risk_level': 'high',
            'last_backup_check': d(days=-90), 'backup_verified': False,
            'dr_plan_documented': False, 'monitoring_active': 'no',
            'website_up': False, 'last_health_check': fields.Datetime.now(),
            'notify_client_on_expiry': False,  # this client asked to be reminded by phone instead
            'tag_ids': [(6, 0, (tag_trial | tag_on_premise).ids)],
            'native_module_ids': native_ids('inventory', 'purchase'),
            'client_it_contact': contacts['nordic'].id,
            'decision_maker_contact': partners['nordic'].id,
            'emergency_contact': contacts['nordic'].id,
        })

        self._ensure_record('demo_asset_nordic_git', 'partner.asset', {
            'name': 'Nordic Tech — Git Repository', 'partner_id': partners['nordic'].id, 'type': 'custom',
            'url': 'https://git.example.com/nordictech/erp',
            'code_repository_branch': 'main',
            'start_date': d(months=-8),
            'monthly_billing_client': 0,
            'stage_id': stage_running.id if stage_running else False,
            'state': 'running', 'risk_level': 'low',
            'tag_ids': [(6, 0, tag_integration.ids)],
        })

        # Blue Harbor — negative margin server, email hosting.
        blueharbor_server = self._ensure_record('demo_asset_blueharbor_server', 'partner.asset', {
            'name': 'Blue Harbor Dedicated Server', 'partner_id': partners['blueharbor'].id, 'type': 'custom',
            'start_date': d(months=-4), 'end_date': d(months=8),
            'reminder_days': 60, 'renewal_period': 12,
            'server_cost': 220, 'license_cost': 16, 'license_count': 5, 'backup_cost': 25, 'external_services_cost': 20,
            'monthly_billing_client': 250,  # underpriced on purpose -> negative margin
            'stage_id': stage_running.id if stage_running else False,
            'state': 'running', 'risk_level': 'medium',
            'monitoring_active': 'yes', 'backup_verified': True, 'dr_plan_documented': True,
            'technical_debt_level': 'high',
            'tag_ids': [(6, 0, tag_support.ids)],
            'native_module_ids': native_ids('inventory', 'purchase', 'accounting'),
            'client_it_contact': contacts['blueharbor'].id,
            'decision_maker_contact': partners['blueharbor'].id,
            'emergency_contact': contacts['blueharbor'].id,
        })

        self._ensure_record('demo_asset_blueharbor_email', 'partner.asset', {
            'name': 'Blue Harbor — Email Hosting', 'partner_id': partners['blueharbor'].id, 'type': 'online',
            'url': 'https://mail.blueharbor.example',
            'subscription_number': 'SUB-BLUEHARBOR-2026-042',
            'start_date': d(months=-2), 'end_date': d(months=10),
            'reminder_days': 60, 'renewal_period': 12,
            'monthly_billing_client': 25,
            'stage_id': stage_running.id if stage_running else False,
            'state': 'running', 'risk_level': 'low',
            'tag_ids': [(6, 0, tag_saas.ids)],
        })

        # Sunrise — just signed, not provisioned yet. Left without a health check
        # or website_up on purpose, so "Check Now" / the cron can be seen live-
        # promoting it from New to Running.
        sunrise_domain = self._ensure_record('demo_asset_sunrise_domain', 'partner.asset', {
            'name': 'sunrisemedia.example', 'partner_id': partners['sunrise'].id, 'type': 'online',
            'url': 'https://sunrisemedia.example',
            'start_date': d(days=-2), 'end_date': d(months=12),
            'reminder_days': 60, 'renewal_period': 12,
            'monthly_billing_client': 12,
            'stage_id': stage_new.id if stage_new else False,
            'state': 'new', 'risk_level': 'low',
            'campaign_id': campaign_ads.id,
            'native_module_ids': native_ids('website', 'ecommerce'),
            'client_it_contact': contacts['sunrise'].id,
            'decision_maker_contact': partners['sunrise'].id,
            'emergency_contact': contacts['sunrise'].id,
        })

        # A couple of custom modules on Acme's Odoo.sh asset.
        self.env['partner.asset.custom.module'].search([
            ('asset_id', '=', acme_sh.id),
        ]).unlink()
        self.env['partner.asset.custom.module'].create([
            {'name': 'ts_partner_app', 'version': '19.7.00', 'author': 'Techman Solutions',
             'asset_id': acme_sh.id},
            {'name': 'l10n_ba_reports', 'version': '19.0.1.0', 'author': 'Techman Solutions',
             'asset_id': acme_sh.id},
        ])

        # A draft renewal quote for the Odoo.sh asset — exactly what clicking
        # "Create Renewal Quote" produces, so there's a live example of the link
        # to confirm and watch the auto date-extension in action.
        product = self.env.ref('ts_partner_app.product_asset_renewal', raise_if_not_found=False)
        env_en = self.env(context={**self.env.context, 'lang': 'en_US'})
        order = env_en.ref(self._xmlid('demo_order_acme_sh_renewal'), raise_if_not_found=False)
        if not (order and order.exists()):
            order = env_en['sale.order'].create({
                'partner_id': partners['acme'].id,
                'origin': acme_sh.name,
            })
            env_en['ir.model.data'].create({
                'name': 'demo_order_acme_sh_renewal', 'module': 'ts_partner_app',
                'model': 'sale.order', 'res_id': order.id, 'noupdate': True,
            })
        if product and not order.order_line:
            env_en['sale.order.line'].create({
                'order_id': order.id, 'product_id': product.id,
                'name': _("Renewal: %(name)s (Odoo.sh)", name=acme_sh.name),
                'product_uom_qty': 1, 'price_unit': acme_sh.monthly_billing_client or 0.0,
            })
        acme_sh.sale_order_id = order.id

        # A follow-up task on the overdue Nordic hosting asset — in the shared
        # "Client Tasks" project, not projectless, or it becomes a private task
        # only its creator can see (and only its creator could later delete via
        # Remove Demo Data — an actual bug hit in testing).
        shared_project = self.env.ref('ts_partner_app.project_client_tasks', raise_if_not_found=False)
        self._ensure_record('demo_task_nordic_renewal', 'project.task', {
            'name': 'Follow up on Nordic VPS renewal',
            'asset_id': nordic_hosting.id,
            'partner_id': partners['nordic'].id,
            'project_id': shared_project.id if shared_project else False,
        })

        # Infrastructure profiles — one Odoo.sh client, one Custom Server client,
        # with credentials populated so the reveal/audit-log flow has something
        # to show.
        self._ensure_record('demo_infra_acme', 'partner.infrastructure', {
            'partner_id': partners['acme'].id, 'hosting_type': 'odoo_sh',
            'odoo_sh_url': 'https://acme-prod.odoo.com', 'odoo_sh_branch': 'production',
            'odoo_sh_database': 'acme-prod-main',
            'odoo_login_url': 'https://acme-prod.odoo.com/odoo',
            'odoo_login_email': 'admin@acme-retail.example',
            'odoo_login_password': 'Demo-Odoo-Pass-2026!',
            'github_url': 'https://github.com/techman-solutions/acme-retail-odoo',
            'github_branch': 'production',
            'github_token': 'ghp_demoAcmeTokenPlaceholder0000',
        })
        self._ensure_record('demo_infra_nordic', 'partner.infrastructure', {
            'partner_id': partners['nordic'].id, 'hosting_type': 'custom_server',
            'server_host': 'vps.nordictech.example', 'server_ssh_port': 22,
            'server_ssh_user': 'deploy', 'hosting_provider': 'Hetzner',
            'odoo_login_url': 'https://vps.nordictech.example/odoo',
            'odoo_login_email': 'admin@nordictech.example',
            'odoo_login_password': 'Demo-Nordic-Pass-2026!',
            'github_url': 'https://github.com/techman-solutions/nordic-tech-odoo',
            'github_branch': 'main',
            'github_token': 'ghp_demoNordicTokenPlaceholder000',
        })
        # Blue Harbor — a SaaS/Odoo Online client with no infra profile on
        # purpose, so the "clients without a profile" dashboard callout has
        # something to point at.

        # A dedicated client project for Acme (as opposed to the shared "Client Tasks"
        # project the Tasks menu uses) — shows what "New Client Project" produces.
        acme_project = self._ensure_record('demo_project_acme', 'project.project', {
            'name': partners['acme'].name, 'partner_id': partners['acme'].id,
        })
        stage_todo = self.env.ref('ts_partner_app.project_task_stage_todo', raise_if_not_found=False)
        stage_in_progress = self.env.ref('ts_partner_app.project_task_stage_in_progress', raise_if_not_found=False)
        stage_waiting = self.env.ref('ts_partner_app.project_task_stage_waiting_client', raise_if_not_found=False)
        stage_done = self.env.ref('ts_partner_app.project_task_stage_done', raise_if_not_found=False)
        (stage_todo | stage_in_progress | stage_waiting | stage_done).write({
            'project_ids': [(4, acme_project.id)],
        })
        self._ensure_record('demo_task_acme_kickoff', 'project.task', {
            'name': 'Kickoff call with Acme IT team',
            'project_id': acme_project.id, 'partner_id': partners['acme'].id,
            'stage_id': stage_done.id if stage_done else False,
        })
        self._ensure_record('demo_task_acme_migration', 'project.task', {
            'name': 'Migrate custom modules to 19.0',
            'project_id': acme_project.id, 'partner_id': partners['acme'].id,
            'asset_id': acme_sh.id, 'stage_id': stage_in_progress.id if stage_in_progress else False,
        })
        self._ensure_record('demo_task_acme_ssl_confirm', 'project.task', {
            'name': 'Confirm SSL renewal window with client',
            'project_id': acme_project.id, 'partner_id': partners['acme'].id,
            'stage_id': stage_waiting.id if stage_waiting else False,
        })
        self._ensure_record('demo_task_acme_training', 'project.task', {
            'name': 'Schedule Odoo 19 training session',
            'project_id': acme_project.id, 'partner_id': partners['acme'].id,
            'stage_id': stage_todo.id if stage_todo else False,
        })

        # Nordic — chasing the overdue hosting renewal.
        nordic_project = self._ensure_record('demo_project_nordic', 'project.project', {
            'name': partners['nordic'].name, 'partner_id': partners['nordic'].id,
        })
        (stage_todo | stage_in_progress | stage_waiting | stage_done).write({
            'project_ids': [(4, nordic_project.id)],
        })
        self._ensure_record('demo_task_nordic_downtime', 'project.task', {
            'name': 'Investigate VPS downtime',
            'project_id': nordic_project.id, 'partner_id': partners['nordic'].id,
            'asset_id': nordic_hosting.id, 'stage_id': stage_in_progress.id if stage_in_progress else False,
        })
        self._ensure_record('demo_task_nordic_backup', 'project.task', {
            'name': 'Set up automated backups',
            'project_id': nordic_project.id, 'partner_id': partners['nordic'].id,
            'asset_id': nordic_hosting.id, 'stage_id': stage_todo.id if stage_todo else False,
        })
        self._ensure_record('demo_task_nordic_terms', 'project.task', {
            'name': 'Confirm renewal terms with client',
            'project_id': nordic_project.id, 'partner_id': partners['nordic'].id,
            'stage_id': stage_waiting.id if stage_waiting else False,
        })

        # Blue Harbor — negative margin needs a pricing conversation.
        blueharbor_project = self._ensure_record('demo_project_blueharbor', 'project.project', {
            'name': partners['blueharbor'].name, 'partner_id': partners['blueharbor'].id,
        })
        (stage_todo | stage_in_progress | stage_waiting | stage_done).write({
            'project_ids': [(4, blueharbor_project.id)],
        })
        self._ensure_record('demo_task_blueharbor_margin', 'project.task', {
            'name': 'Review infra costs vs. billing (negative margin)',
            'project_id': blueharbor_project.id, 'partner_id': partners['blueharbor'].id,
            'asset_id': blueharbor_server.id, 'stage_id': stage_todo.id if stage_todo else False,
        })
        self._ensure_record('demo_task_blueharbor_monitoring', 'project.task', {
            'name': 'Enable uptime monitoring alerts',
            'project_id': blueharbor_project.id, 'partner_id': partners['blueharbor'].id,
            'asset_id': blueharbor_server.id, 'stage_id': stage_in_progress.id if stage_in_progress else False,
        })
        self._ensure_record('demo_task_blueharbor_review_call', 'project.task', {
            'name': 'Quarterly margin review call',
            'project_id': blueharbor_project.id, 'partner_id': partners['blueharbor'].id,
            'stage_id': stage_waiting.id if stage_waiting else False,
        })

        # Sunrise — just signed, still onboarding.
        sunrise_project = self._ensure_record('demo_project_sunrise', 'project.project', {
            'name': partners['sunrise'].name, 'partner_id': partners['sunrise'].id,
        })
        (stage_todo | stage_in_progress | stage_waiting | stage_done).write({
            'project_ids': [(4, sunrise_project.id)],
        })
        self._ensure_record('demo_task_sunrise_provision', 'project.task', {
            'name': 'Provision new client environment',
            'project_id': sunrise_project.id, 'partner_id': partners['sunrise'].id,
            'asset_id': sunrise_domain.id, 'stage_id': stage_in_progress.id if stage_in_progress else False,
        })
        self._ensure_record('demo_task_sunrise_kickoff', 'project.task', {
            'name': 'Schedule kickoff call',
            'project_id': sunrise_project.id, 'partner_id': partners['sunrise'].id,
            'stage_id': stage_todo.id if stage_todo else False,
        })
        self._ensure_record('demo_task_sunrise_welcome', 'project.task', {
            'name': 'Send welcome & onboarding guide',
            'project_id': sunrise_project.id, 'partner_id': partners['sunrise'].id,
            'stage_id': stage_done.id if stage_done else False,
        })

        action = self.env['ir.actions.actions']._for_xml_id('ts_partner_app.partner_asset_action')
        return action

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------
    def action_remove_demo_data(self):
        self.ensure_one()
        data = self.env['ir.model.data'].search([
            ('module', '=', 'ts_partner_app'),
        ]).filtered(lambda d: d.name.startswith('demo_'))
        if not data:
            raise UserError(_("No demo data found — nothing to remove."))

        # Unlink child records before their parents to respect FKs:
        # tasks/orders first, then assets/infra, then contacts/partners/tags last.
        by_model = {}
        for entry in data:
            by_model.setdefault(entry.model, self.env[entry.model])
            by_model[entry.model] |= self.env[entry.model].browse(entry.res_id).exists()

        order = ['project.task', 'project.project', 'sale.order', 'partner.infrastructure',
                 'partner.asset', 'partner.asset.tag', 'utm.campaign', 'res.partner']
        for model in order:
            records = by_model.pop(model, None)
            if records:
                records.unlink()
        for records in by_model.values():
            if records:
                records.unlink()

        data.unlink()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
