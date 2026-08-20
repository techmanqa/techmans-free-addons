# The Status field ("state") gets a new 'new' value to match the "New" Kanban
# stage (added in 19.7.13). Existing assets already sitting in the New stage were
# created before this and show state='running' (the old only-ever-used default),
# which reads as a contradiction (stage "New" next to a "Running" badge). Fix the
# ones actually affected — anything currently in the New stage — and leave every
# other asset's status untouched.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'ts_partner_app' AND name = 'stage_new'
    """)
    row = cr.fetchone()
    if not row:
        return
    stage_new_id = row[0]

    cr.execute("""
        UPDATE partner_asset
        SET state = 'new'
        WHERE stage_id = %s AND state = 'running'
    """, (stage_new_id,))
    _logger.info("ts_partner_app: corrected status to 'New' on %s asset(s) already sitting "
                "in the New stage.", cr.rowcount)
