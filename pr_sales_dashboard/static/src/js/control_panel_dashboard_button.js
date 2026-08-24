/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService } from "@web/core/utils/hooks";

patch(ControlPanel.prototype, {
    setup() {
        super.setup();
        this.prSalesDashboardAction = useService("action");
    },

    get prShowSalesDashboardButton() {
        return this.env.searchModel?.resModel === "sale.order";
    },

    onClickPrSalesDashboard() {
        this.prSalesDashboardAction.doAction("pr_sales_dashboard.action_pr_sales_dashboard");
    },
});
