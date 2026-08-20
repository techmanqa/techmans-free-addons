from datetime import datetime, time, timedelta
from math import ceil

from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Phases pre-selected by default: the "always needed" implementation phases.
# Modules and integrations vary too much per client to guess, so they start unchecked.
_DEFAULT_SELECTED_PHASES = {'discovery', 'foundation', 'migration', 'testing', 'training', 'pm'}

# Order tasks are scheduled/created in, matching the natural project flow (not just each
# template's per-phase sequence, which restarts at 10 in every phase).
_PHASE_ORDER = ['discovery', 'foundation', 'modules', 'migration', 'integration', 'testing', 'training', 'pm']

# Business-day scheduling: tasks are packed onto a day up to this many hours; a single
# task longer than that spans consecutive business days instead of being split.
_DAILY_CAPACITY_HOURS = 12.0
_WORKDAY_START = time(9, 0)
_WORKDAY_END = time(17, 0)


def _next_business_day(d):
    d = d + timedelta(days=1)
    while d.weekday() >= 5:  # Sat/Sun
        d += timedelta(days=1)
    return d


def _roll_to_business_day(d):
    while d.weekday() >= 5:
        d = _next_business_day(d - timedelta(days=1))
    return d


def _schedule_lines(ordered_lines, start_date):
    """Pack lines onto business days, up to _DAILY_CAPACITY_HOURS/day; a task whose own
    hours exceed that spans consecutive business days instead. Returns {line: (begin, end)}
    as dates."""
    current_date = _roll_to_business_day(start_date)
    day_hours_used = 0.0
    schedule = {}
    for line in ordered_lines:
        hours = line.planned_hours or 0.0
        if day_hours_used and day_hours_used + hours > _DAILY_CAPACITY_HOURS:
            current_date = _next_business_day(current_date)
            day_hours_used = 0.0
        if hours > _DAILY_CAPACITY_HOURS:
            end_date = current_date
            for _ in range(ceil(hours / _DAILY_CAPACITY_HOURS) - 1):
                end_date = _next_business_day(end_date)
            schedule[line] = (current_date, end_date)
            current_date = _next_business_day(end_date)
            day_hours_used = 0.0
        else:
            schedule[line] = (current_date, current_date)
            day_hours_used += hours
    return schedule

# Which One2many field on the wizard each template phase's lines are created under.
# One line per phase key, no overlap — each template task ends up in exactly one field,
# so default_get can populate every field directly (see note on _compute_totals below).
_PHASE_FIELD_MAP = {
    'modules': 'line_modules_ids',
    'discovery': 'line_discovery_foundation_ids',
    'foundation': 'line_discovery_foundation_ids',
    'migration': 'line_migration_ids',
    'integration': 'line_integration_ids',
    'testing': 'line_testing_training_ids',
    'training': 'line_testing_training_ids',
    'pm': 'line_pm_ids',
}
_ALL_LINE_FIELDS = list(dict.fromkeys(_PHASE_FIELD_MAP.values()))


class PartnerProjectTemplateWizard(models.TransientModel):
    _name = 'partner.project.template.wizard'
    _description = 'New Client Project Wizard'

    state = fields.Selection([('tasks', 'Tasks'), ('modules', 'Modules')], default='tasks', required=True)
    start_date = fields.Date(string='Project Start Date', required=True, default=fields.Date.context_today,
                              help="Selected tasks are auto-scheduled from this date: packed onto business "
                                   "days up to 12h/day, with longer tasks spanning consecutive days.")
    asset_id = fields.Many2one('partner.asset', required=True)
    partner_id = fields.Many2one(related='asset_id.partner_id', string='Client', readonly=True)
    existing_project_id = fields.Many2one(related='asset_id.client_project_id', string='Existing Project',
                                           readonly=True)
    # Six real One2many fields sharing the same inverse ('wizard_id'), one per wizard page.
    # default_get populates each directly (no shared/undomained field) so the web client's
    # local cache for a brand-new, unsaved record has data for every one of them from the start.
    line_modules_ids = fields.One2many('partner.project.template.wizard.line', 'wizard_id',
                                        domain=[('phase', '=', 'modules')], string='Modules')
    line_discovery_foundation_ids = fields.One2many('partner.project.template.wizard.line', 'wizard_id',
                                                      domain=[('phase', 'in', ('discovery', 'foundation'))],
                                                      string='Discovery & Foundation')
    line_migration_ids = fields.One2many('partner.project.template.wizard.line', 'wizard_id',
                                          domain=[('phase', '=', 'migration')], string='Data Migration')
    line_integration_ids = fields.One2many('partner.project.template.wizard.line', 'wizard_id',
                                            domain=[('phase', '=', 'integration')],
                                            string='Integrations & Customization')
    line_testing_training_ids = fields.One2many('partner.project.template.wizard.line', 'wizard_id',
                                                 domain=[('phase', 'in', ('testing', 'training'))],
                                                 string='Testing & Training')
    line_pm_ids = fields.One2many('partner.project.template.wizard.line', 'wizard_id',
                                   domain=[('phase', '=', 'pm')], string='Project Management')
    selected_count = fields.Integer(compute='_compute_totals')
    total_hours = fields.Float(compute='_compute_totals', string='Total Selected Hours')

    def _all_lines(self):
        self.ensure_one()
        lines = self.env['partner.project.template.wizard.line']
        for field_name in _ALL_LINE_FIELDS:
            lines |= self[field_name]
        return lines

    @api.depends(*[f'{fname}.selected' for fname in _ALL_LINE_FIELDS],
                 *[f'{fname}.planned_hours' for fname in _ALL_LINE_FIELDS])
    def _compute_totals(self):
        for wizard in self:
            selected = wizard._all_lines().filtered('selected')
            wizard.selected_count = len(selected)
            wizard.total_hours = sum(selected.mapped('planned_hours'))

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        wizards._populate_lines()
        return wizards

    def _populate_lines(self):
        """Create the 49 catalog lines for each wizard, split across the 6 page fields.
        Done as an explicit write right after create() (not via default_get) so the wizard
        is a fully-persisted record with real child rows before the dialog ever opens —
        no unsaved/virtual-record x2many state for the web client to lose track of."""
        templates = self.env['partner.project.template.task'].search([])
        Line = self.env['partner.project.template.wizard.line']
        for wizard in self:
            Line.create([{
                'wizard_id': wizard.id,
                'template_task_id': tmpl.id,
                'sequence': tmpl.sequence,
                'name': tmpl.name,
                'phase': tmpl.phase,
                'note': tmpl.note,
                'default_hours': tmpl.default_hours,
                'planned_hours': tmpl.default_hours,
                'selected': tmpl.phase in _DEFAULT_SELECTED_PHASES,
            } for tmpl in templates])

    def _reopen(self):
        """Reopen this (already-persisted) wizard in place. A type="object" button that
        returns nothing closes a target="new" dialog by default — returning this instead
        keeps it open. Safe now that the wizard is always a real DB row before the dialog
        opens (a plain read(), not the fragile from-scratch create() that caused earlier
        bugs when this was reopening an unsaved/virtual record)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_goto_modules(self):
        self.state = 'modules'
        return self._reopen()

    def action_recalc_pm(self):
        """Set the 'Status meetings, reporting, coordination' line to 12.5% (midpoint
        of the usual 10-15%) of all other currently-selected hours."""
        self.ensure_one()
        other_lines = self._all_lines() - self.line_pm_ids
        base = sum(other_lines.filtered('selected').mapped('planned_hours'))
        status_tmpl = self.env.ref('ts_partner_app.tmpl_pm_status_meetings', raise_if_not_found=False)
        status_line = self.line_pm_ids.filtered(lambda l: l.template_task_id == status_tmpl)
        if status_line:
            status_line.planned_hours = round(base * 0.125, 1)
            status_line.selected = True
        return self._reopen()

    def action_create_project(self):
        self.ensure_one()
        selected = self._all_lines().filtered('selected')
        if not selected:
            raise UserError(_("Select at least one task before creating the project."))

        project = self.asset_id._get_or_create_client_project()
        if not project.date_start:
            project.date_start = self.start_date
        todo_stage = self.env.ref('ts_partner_app.project_task_stage_todo', raise_if_not_found=False)
        phase_tags = self._get_phase_tags()

        phase_index = {phase: index for index, phase in enumerate(_PHASE_ORDER)}
        ordered = selected.sorted(key=lambda l: (phase_index.get(l.phase, 99), l.sequence))
        schedule = _schedule_lines(ordered, self.start_date)
        has_planned_begin = 'planned_date_begin' in self.env['project.task']._fields

        tasks_vals = []
        for line in ordered:
            begin_date, end_date = schedule[line]
            vals = {
                'name': line.name,
                'project_id': project.id,
                'partner_id': self.partner_id.id,
                'stage_id': todo_stage.id if todo_stage else False,
                'allocated_hours': line.planned_hours,
                'tag_ids': [(4, phase_tags[line.phase].id)] if line.phase in phase_tags else False,
                'date_deadline': datetime.combine(end_date, _WORKDAY_END),
            }
            if has_planned_begin:
                vals['planned_date_begin'] = datetime.combine(begin_date, _WORKDAY_START)
            tasks_vals.append(vals)
        self.env['project.task'].create(tasks_vals)

        self.asset_id.message_post(body=_(
            "%(count)s tasks added to project %(project)s from the implementation template, "
            "scheduled from %(start)s.",
            count=len(tasks_vals), project=project.name, start=self.start_date))
        return project.action_view_tasks()

    def _get_phase_tags(self):
        Tag = self.env['project.tags']
        labels = dict(self.env['partner.project.template.wizard.line']._fields['phase'].selection)
        result = {}
        for key, label in labels.items():
            tag = Tag.search([('name', '=', label)], limit=1)
            if not tag:
                tag = Tag.create({'name': label})
            result[key] = tag
        return result


class PartnerProjectTemplateWizardLine(models.TransientModel):
    _name = 'partner.project.template.wizard.line'
    _description = 'New Client Project Wizard Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('partner.project.template.wizard', required=True, ondelete='cascade')
    template_task_id = fields.Many2one('partner.project.template.task')
    sequence = fields.Integer(default=10)
    phase = fields.Selection([
        ('discovery', 'Discovery & Planning'),
        ('foundation', 'Environment & Foundation'),
        ('modules', 'Module Configuration'),
        ('migration', 'Data Migration'),
        ('integration', 'Integrations & Customization'),
        ('testing', 'Testing'),
        ('training', 'Training & Go-Live'),
        ('pm', 'Project Management'),
    ], required=True)
    name = fields.Char(required=True)
    note = fields.Char(readonly=True)
    default_hours = fields.Float(readonly=True)
    planned_hours = fields.Float(string='Hours')
    selected = fields.Boolean(default=False)
