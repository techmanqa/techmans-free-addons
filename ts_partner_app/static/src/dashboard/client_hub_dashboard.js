/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, proxy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ClientHubDashboard extends Component {
    static template = "ts_partner_app.ClientHubDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = proxy({ data: null, error: false, loading: false });
        this.riskCards = [
            { key: "high_risk_count", label: "High risk", icon: "warning", tone: "danger", open: () => this.openHighRisk() },
            { key: "down_count", label: "Unreachable", icon: "power", tone: "danger", open: () => this.openDown() },
            { key: "backup_stale_count", label: "Backup stale", icon: "database", tone: "warning", open: () => this.openBackupStale() },
            { key: "negative_margin_count", label: "Negative margin", icon: "arrow_downward", tone: "warning", open: () => this.openNegativeMargin() },
            { key: "upgrades_due_count", label: "Odoo upgrades due", icon: "arrow_upward", tone: "warning", open: () => this.openUpgradesDue() },
        ];

        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("partner.asset", "get_dashboard_data", []);
            this.state.error = false;
        } catch {
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }

    refresh() {
        return this.loadData();
    }

    get todayLabel() {
        return new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    }

    get riskTotal() {
        const risk = this.state.data?.risk || {};
        return this.riskCards.reduce((sum, card) => sum + (risk[card.key] || 0), 0);
    }

    marginWidth(pct) {
        return Math.max(0, Math.min(100, Math.round(pct || 0)));
    }

    _daysUntil(dateStr) {
        if (!dateStr) {
            return null;
        }
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        return Math.round((new Date(`${dateStr}T00:00:00`) - today) / 86400000);
    }

    expiryLabel(dateStr) {
        const days = this._daysUntil(dateStr);
        if (days === null) {
            return "";
        }
        if (days < 0) {
            return `${-days}d overdue`;
        }
        return days === 0 ? "Today" : `in ${days}d`;
    }

    expiryClass(dateStr) {
        const days = this._daysUntil(dateStr);
        return days !== null && days <= 7 ? "o_ch_date_urgent" : "";
    }

    formatMoney(amount) {
        const data = this.state.data;
        const rounded = Math.round(amount || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
        if (!data) {
            return rounded;
        }
        return data.currency_position === "after"
            ? `${rounded}\u00a0${data.currency_symbol}`
            : `${data.currency_symbol}${rounded}`;
    }

    formatPct(value) {
        return `${(value || 0).toFixed(1)}%`;
    }

    barPct(count) {
        const total = this.state.data.kpi.asset_count || 1;
        return Math.round((count / total) * 100);
    }

    infraBarPct(count) {
        const total = this.state.data.infrastructure.by_hosting_type.reduce((sum, r) => sum + r.count, 0) || 1;
        return Math.round((count / total) * 100);
    }

    openAssets(domain, name, context) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "partner.asset",
            name: name || "Client Assets",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain,
            context: context || {},
        });
    }

    openClients() {
        this.openAssets(
            [["state", "!=", "closed"]],
            "Clients",
            { group_by: "partner_id" }
        );
    }

    openActiveAssets() {
        this.openAssets([["state", "!=", "closed"]], "Active Client Assets");
    }

    openAsset(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "partner.asset",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openByType(row) {
        this.openAssets([["type", "=", row.type], ["state", "!=", "closed"]], row.label);
    }

    openInfraByHostingType(row) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "partner.infrastructure",
            name: row.label,
            views: [[false, "list"], [false, "form"]],
            domain: [["hosting_type", "=", row.hosting_type]],
        });
    }

    openProjects() {
        this.actionService.doAction("ts_partner_app.partner_asset_project_action");
    }

    openNewClientAsset() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "New Client Asset",
            res_model: "partner.asset",
            views: [[false, "form"]],
            target: "current",
        });
    }

    projectBarPct(count) {
        const total = this.state.data.projects.by_stage.reduce((sum, r) => sum + r.count, 0) || 1;
        return Math.round((count / total) * 100);
    }

    openTasksByStage(row) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            name: row.label,
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: [["project_id", "in", this.state.data.projects.project_ids], ["stage_id", "=", row.stage_id]],
        });
    }

    openAllProjectTasks() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            name: "Client Project Tasks",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: [["project_id", "in", this.state.data.projects.project_ids]],
        });
    }

    openMissingInfra() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            name: "Clients without an Infrastructure Profile",
            views: [[false, "list"], [false, "form"]],
            domain: [["id", "in", this.state.data.infrastructure.missing_partner_ids]],
        });
    }

    openExpiringSoon() {
        this.openAssets(
            [["expiry_date", "!=", false], ["expiry_date", "<=", this._daysFromNow(30)], ["state", "!=", "closed"]],
            "Expiring Soon"
        );
    }

    openHighRisk() {
        this.openAssets([["risk_level", "=", "high"], ["state", "!=", "closed"]], "High Risk Assets");
    }

    openEnvironments(domain, name) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "partner.environment",
            name: name,
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            context: {},
        });
    }

    openDown() {
        this.openEnvironments(
            [["website_up", "=", false], ["last_health_check", "!=", false]],
            "Unreachable Environments"
        );
    }

    openBackupStale() {
        this.openEnvironments(
            ["|", ["last_backup_check", "=", false], ["last_backup_check", "<", this._daysFromNow(-60)]],
            "Backup Not Verified"
        );
    }

    openNegativeMargin() {
        this.openAssets([["gross_margin", "<", 0], ["state", "!=", "closed"]], "Negative Margin");
    }

    openUpgradesDue() {
        this.openEnvironments(
            [["id", "in", this.state.data.risk.upgrades_due_ids]],
            "Odoo Upgrades Due"
        );
    }

    _daysFromNow(days) {
        const d = new Date();
        d.setDate(d.getDate() + days);
        return d.toISOString().slice(0, 10);
    }
}

registry.category("actions").add("ts_partner_app.dashboard", ClientHubDashboard);
