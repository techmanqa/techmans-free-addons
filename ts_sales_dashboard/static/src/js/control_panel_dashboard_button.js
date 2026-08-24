/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService } from "@web/core/utils/hooks";

patch(ControlPanel.prototype, {
    setup() {
        super.setup();
        this.tsSalesDashboardAction = useService("action");
    },

    get tsShowSalesDashboardButton() {
        return this.env.searchModel?.resModel === "sale.order";
    },

    onClickTsSalesDashboard() {
        this.tsSalesDashboardAction.doAction("ts_sales_dashboard.action_ts_sales_dashboard");
    },
});
