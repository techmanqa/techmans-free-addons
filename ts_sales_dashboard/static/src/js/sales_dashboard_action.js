/** @odoo-module **/

import { Component, onWillStart, useExternalListener, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";

export const DATE_RANGE_OPTIONS = [
    { id: "all_time", label: _t("All Time") },
    { id: "this_year", label: _t("This Year") },
    { id: "last_year", label: _t("Last Year") },
    { id: "this_quarter", label: _t("This Quarter") },
    { id: "last_6_months", label: _t("Last 6 Months") },
    { id: "last_12_months", label: _t("Last 12 Months") },
    { id: "custom", label: _t("Custom Range") },
];

export const CARD_DEFINITIONS = [
    { id: "total-revenue", label: _t("Total Revenue & Orders") },
    { id: "monthly-trends", label: _t("Monthly Sales Revenue Trends") },
    { id: "customer-insights", label: _t("Customer Requisition Insights") },
    { id: "new-customers-gauge", label: _t("Sale Orders from New Customers") },
    { id: "repeat-customers-gauge", label: _t("Sale Orders from Repeat Customers") },
    { id: "average-order-value", label: _t("Average Order Value") },
    { id: "conversion", label: _t("Quotation Conversion Rate") },
    { id: "invoicing-status", label: _t("Invoicing Status") },
    { id: "best-client", label: _t("Best Client") },
    { id: "red-client", label: _t("Red Client (Most Cancelled)") },
    { id: "product-categories", label: _t("Sales Revenue by Product Category") },
    { id: "top-products-revenue", label: _t("Top 5 Highest Revenue-Generating Products") },
    { id: "salespeople", label: _t("Sales by Salesperson") },
    { id: "geography", label: _t("Geographical Sales Analysis") },
    { id: "top-products-volume", label: _t("Top 5 Best-Selling Products by Volume") },
    { id: "top-customers-bars", label: _t("Sales Revenue From Top 5 Customers") },
    { id: "teams", label: _t("Revenue Target Achievement by Sales Teams") },
    { id: "lost-pipeline", label: _t("Lost Pipeline (Cancelled Quotations)") },
    { id: "quotation-aging", label: _t("Open Quotation Aging") },
];

export class SalesDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.cardDefinitions = CARD_DEFINITIONS;
        this.dateRangeOptions = DATE_RANGE_OPTIONS;
        this.storageKey = `ts_sales_dashboard_hidden_cards_${user.userId || "anon"}`;
        this.settingsRef = useRef("settingsRoot");
        this.dateFilterRef = useRef("dateFilterRoot");
        this.state = useState({
            data: {},
            loading: true,
            months: 6,
            showSettings: false,
            hiddenCards: this.loadHiddenCards(),
            activeInfo: null,
            dateRangeKey: "all_time",
            customDateFrom: false,
            customDateTo: false,
            showDateFilter: false,
        });

        useExternalListener(window, "click", (ev) => {
            if (
                this.state.showSettings &&
                this.settingsRef.el &&
                !this.settingsRef.el.contains(ev.target)
            ) {
                this.state.showSettings = false;
            }
            if (
                this.state.showDateFilter &&
                this.dateFilterRef.el &&
                !this.dateFilterRef.el.contains(ev.target)
            ) {
                this.state.showDateFilter = false;
            }
            if (this.state.activeInfo && !ev.target.closest(".pr-sales-info-wrap")) {
                this.state.activeInfo = null;
            }
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    loadHiddenCards() {
        try {
            const raw = localStorage.getItem(this.storageKey);
            return raw ? JSON.parse(raw) : [];
        } catch {
            return [];
        }
    }

    saveHiddenCards() {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify(this.state.hiddenCards));
        } catch {
            // localStorage unavailable (private browsing, quota) - fail silently
        }
    }

    isCardHidden(id) {
        return this.state.hiddenCards.includes(id);
    }

    toggleCard(id) {
        const index = this.state.hiddenCards.indexOf(id);
        if (index === -1) {
            this.state.hiddenCards.push(id);
        } else {
            this.state.hiddenCards.splice(index, 1);
        }
        this.saveHiddenCards();
    }

    toggleSettingsPanel() {
        this.state.showSettings = !this.state.showSettings;
    }

    toggleInfo(id) {
        this.state.activeInfo = this.state.activeInfo === id ? null : id;
    }

    async loadDashboardData() {
        this.state.loading = true;
        const { date_from, date_to } = this.computeDateRange(this.state.dateRangeKey);
        this.state.data = await this.orm.call(
            "ts.sales.dashboard",
            "get_dashboard_data",
            [this.state.months, date_from, date_to]
        );
        this.state.loading = false;
    }

    async setPeriod(months) {
        if (this.state.months === months) {
            return;
        }
        this.state.months = months;
        await this.loadDashboardData();
    }

    computeDateRange(key) {
        const today = new Date();
        const pad = (value) => String(value).padStart(2, "0");
        const toISO = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
        switch (key) {
            case "this_year":
                return { date_from: toISO(new Date(today.getFullYear(), 0, 1)), date_to: toISO(today) };
            case "last_year":
                return {
                    date_from: toISO(new Date(today.getFullYear() - 1, 0, 1)),
                    date_to: toISO(new Date(today.getFullYear() - 1, 11, 31)),
                };
            case "this_quarter": {
                const quarterStartMonth = Math.floor(today.getMonth() / 3) * 3;
                return { date_from: toISO(new Date(today.getFullYear(), quarterStartMonth, 1)), date_to: toISO(today) };
            }
            case "last_6_months":
                return { date_from: toISO(new Date(today.getFullYear(), today.getMonth() - 5, 1)), date_to: toISO(today) };
            case "last_12_months":
                return { date_from: toISO(new Date(today.getFullYear(), today.getMonth() - 11, 1)), date_to: toISO(today) };
            case "custom":
                return { date_from: this.state.customDateFrom || false, date_to: this.state.customDateTo || false };
            case "all_time":
            default:
                return { date_from: false, date_to: false };
        }
    }

    toggleDateFilter() {
        this.state.showDateFilter = !this.state.showDateFilter;
    }

    async setDateRange(key) {
        if (key === "custom") {
            this.state.dateRangeKey = "custom";
            return;
        }
        this.state.showDateFilter = false;
        if (this.state.dateRangeKey === key) {
            return;
        }
        this.state.dateRangeKey = key;
        await this.loadDashboardData();
    }

    async applyCustomRange() {
        if (!this.state.customDateFrom || !this.state.customDateTo) {
            return;
        }
        this.state.showDateFilter = false;
        await this.loadDashboardData();
    }

    get dateRangeLabel() {
        if (this.state.dateRangeKey === "custom") {
            return this.state.customDateFrom && this.state.customDateTo
                ? `${this.state.customDateFrom} → ${this.state.customDateTo}`
                : _t("Custom Range");
        }
        const option = this.dateRangeOptions.find((item) => item.id === this.state.dateRangeKey);
        return option ? option.label : _t("All Time");
    }

    openRecords(model, domain = [], name = "Records") {
        if (!model) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    formatMoney(value) {
        const currency = this.state.data.currency || {};
        const amount = Number(value || 0);
        const digits = Math.abs(amount) >= 1000 ? 0 : Math.min(currency.digits ?? 2, 2);
        const formatted = new Intl.NumberFormat(undefined, {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        }).format(amount);
        const symbol = currency.symbol || "";
        return currency.position === "after" ? `${formatted} ${symbol}`.trim() : `${symbol}${formatted}`.trim();
    }

    formatNumber(value) {
        return new Intl.NumberFormat(undefined, {
            maximumFractionDigits: 2,
        }).format(Number(value || 0));
    }

    formatPercent(value) {
        return `${Math.round(Number(value || 0))}%`;
    }

    deltaClass(value) {
        if (value === null || value === undefined) {
            return "pr-sales-delta";
        }
        if (value > 0) {
            return "pr-sales-delta pr-sales-delta-up";
        }
        if (value < 0) {
            return "pr-sales-delta pr-sales-delta-down";
        }
        return "pr-sales-delta pr-sales-delta-flat";
    }

    deltaLabel(value) {
        if (value === null || value === undefined) {
            return "";
        }
        const rounded = Math.round(value * 10) / 10;
        const arrow = rounded > 0 ? "▲" : rounded < 0 ? "▼" : "•";
        return `${arrow} ${Math.abs(rounded)}%`;
    }

    clampPercent(value) {
        return Math.max(0, Math.min(100, Number(value || 0)));
    }

    donutStyle(value, color = "#2f95ed") {
        const percent = this.clampPercent(value);
        return `background: conic-gradient(${color} 0 ${percent}%, #e7edf4 ${percent}% 100%);`;
    }

    gaugeStyle(value, color = "#2f95ed") {
        const percent = this.clampPercent(value);
        return `--gauge-value:${percent / 2}%; --gauge-color:${color};`;
    }

    agingColor(bucketId) {
        const colors = {
            "0_7": "#18cf93",
            "8_30": "#ffbd45",
            "31_90": "#ff8a3d",
            "90_plus": "#ff5a66",
        };
        return colors[bucketId] || "#2f95ed";
    }

    monthlyMax(monthly = []) {
        const confirmed = monthly.map((item) => Number(item.revenue || 0));
        const option = monthly.map((item) => Number(item.option_revenue || 0));
        return Math.max(...confirmed, ...option, 0);
    }

    linePoints(monthly = [], key = "revenue") {
        const width = 520;
        const height = 150;
        const pad = 10;
        if (!monthly.length) {
            return "";
        }
        const max = this.monthlyMax(monthly);
        if (!max) {
            return monthly.map((item, index) => {
                const x = pad + (index * (width - pad * 2)) / Math.max(monthly.length - 1, 1);
                return `${x},${height / 2}`;
            }).join(" ");
        }
        return monthly.map((item, index) => {
            const x = pad + (index * (width - pad * 2)) / Math.max(monthly.length - 1, 1);
            const y = height - pad - ((Number(item[key] || 0) / max) * (height - pad * 2));
            return `${x},${y}`;
        }).join(" ");
    }

    lineAreaPoints(monthly = [], key = "revenue") {
        const points = this.linePoints(monthly, key);
        if (!points) {
            return "";
        }
        return `10,150 ${points} 510,150`;
    }

    sparklinePoints(monthly = []) {
        const width = 150;
        const height = 58;
        const values = monthly.map((item) => Number(item.revenue || 0));
        const max = Math.max(...values, 0);
        if (!monthly.length) {
            return "";
        }
        return monthly.map((item, index) => {
            const x = (index * width) / Math.max(monthly.length - 1, 1);
            const y = max ? height - ((Number(item.revenue || 0) / max) * height) : height / 2;
            return `${x},${y}`;
        }).join(" ");
    }
}

SalesDashboardAction.template = "ts_sales_dashboard.SalesDashboardAction";

registry.category("actions").add("ts_sales_dashboard.sales_dashboard", SalesDashboardAction);
