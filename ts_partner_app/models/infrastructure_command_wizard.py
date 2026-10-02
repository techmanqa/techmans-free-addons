from markupsafe import Markup

from odoo import models, fields, _


class InfrastructureCommandWizard(models.TransientModel):
    _name = 'partner.infrastructure.command.wizard'
    _description = 'Run a Maintenance Command on a Client Server'

    infrastructure_id = fields.Many2one('partner.infrastructure', string='Server',
                                        required=True, readonly=True, ondelete='cascade')
    command = fields.Char(string='Command', required=True)
    output = fields.Text(string='Output', readonly=True)

    def action_run(self):
        """Run the command over SSH, show the output, and keep the popup open
        so another command can be run right away."""
        self.ensure_one()
        exit_status, out, err = self.infrastructure_id._ssh_run(self.command, timeout=30)
        parts = []
        if (out or '').strip():
            parts.append(out.strip())
        if (err or '').strip():
            parts.append("[stderr]\n" + err.strip())
        self.output = "\n\n".join(parts) or _("(no output, exit status %s)", exit_status)

        self.infrastructure_id.message_post(body=Markup("%s<pre>%s</pre>") % (
            _("Command run: %s", self.command), self.output,
        ))

        return {
            'name': _("Run Command"),
            'type': 'ir.actions.act_window',
            'res_model': 'partner.infrastructure.command.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
