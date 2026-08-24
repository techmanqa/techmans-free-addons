# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models


class TsSalesDashboard(models.AbstractModel):
    _name = "ts.sales.dashboard"
    _description = "Executive Sales Dashboard Service"

    @api.model
    def get_dashboard_data(self, months=6, date_from=False, date_to=False):
        state_domain = [("state", "in", ["sale", "done"])]
        date_domain = self._date_domain(date_from, date_to)
        line_date_domain = [("order_id." + field, op, value) for field, op, value in date_domain]

        confirmed_domain = state_domain + date_domain
        confirmed_domain_ui = [["state", "in", ["sale", "done"]]] + [list(cond) for cond in date_domain]
        line_domain = [
            ("order_id.state", "in", ["sale", "done"]),
            ("display_type", "=", False),
            ("product_id", "!=", False),
        ] + line_date_domain

        summary = self._get_summary(confirmed_domain, confirmed_domain_ui)
        customers = self._get_customer_insights(confirmed_domain)
        monthly = self._get_monthly_revenue(state_domain, months=months)
        product_data = self._get_product_data(line_domain, line_date_domain)
        top_customers = self._get_top_customers(confirmed_domain, date_domain)
        geography = self._get_geography(confirmed_domain, date_domain)
        teams = self._get_team_achievement(confirmed_domain, date_domain)
        conversion = self._get_conversion(date_domain)
        comparison = self._get_comparison(state_domain, date_from, date_to, summary, conversion)

        return {
            "summary": summary,
            "months": months,
            "monthly": monthly,
            "customers": customers,
            "product_categories": product_data["categories"],
            "top_products_revenue": product_data["top_revenue"],
            "top_products_volume": product_data["top_volume"],
            "salespeople": self._get_salespeople(confirmed_domain, date_domain),
            "top_customers": top_customers,
            "best_client": self._get_best_client(confirmed_domain, date_domain),
            "red_client": self._get_red_client(date_domain),
            "conversion": conversion,
            "geography": geography,
            "teams": teams,
            "currency": self._currency_data(),
            "date_range": {"date_from": date_from, "date_to": date_to},
            "comparison": comparison,
            "lost_pipeline": self._get_lost_pipeline(months=6),
            "invoicing": self._get_invoicing(confirmed_domain, confirmed_domain_ui),
            "quotation_aging": self._get_quotation_aging(),
        }

    def _date_domain(self, date_from, date_to):
        domain = []
        if date_from:
            start_dt = fields.Datetime.to_string(datetime.combine(fields.Date.from_string(date_from), time.min))
            domain.append(("date_order", ">=", start_dt))
        if date_to:
            end_dt = fields.Datetime.to_string(datetime.combine(fields.Date.from_string(date_to), time.max))
            domain.append(("date_order", "<=", end_dt))
        return domain

    def _get_comparison(self, state_domain, date_from, date_to, summary, conversion):
        if not date_from or not date_to:
            return False

        start = fields.Date.from_string(date_from)
        end = fields.Date.from_string(date_to)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - (end - start)
        prev_date_from = fields.Date.to_string(prev_start)
        prev_date_to = fields.Date.to_string(prev_end)

        prev_date_domain = self._date_domain(prev_date_from, prev_date_to)
        prev_confirmed_domain = state_domain + prev_date_domain

        Order = self.env["sale.order"]
        totals = Order.read_group(prev_confirmed_domain, ["amount_total:sum"], [])
        prev_revenue = totals[0].get("amount_total", 0.0) if totals else 0.0
        prev_orders = Order.search_count(prev_confirmed_domain)
        prev_average_order_value = prev_revenue / prev_orders if prev_orders else 0.0
        prev_quotations = Order.search_count(prev_date_domain)
        prev_conversion_rate = self._percent(prev_orders, prev_quotations)

        return {
            "date_from": prev_date_from,
            "date_to": prev_date_to,
            "revenue": prev_revenue,
            "revenue_change": self._change_percent(summary["total_revenue"], prev_revenue),
            "orders": prev_orders,
            "orders_change": self._change_percent(summary["total_orders"], prev_orders),
            "average_order_value": prev_average_order_value,
            "average_order_value_change": self._change_percent(summary["average_order_value"], prev_average_order_value),
            "conversion_rate": prev_conversion_rate,
            "conversion_rate_change": self._change_percent(conversion["conversion_rate"], prev_conversion_rate),
        }

    def _change_percent(self, current, previous):
        current = float(current or 0.0)
        previous = float(previous or 0.0)
        if not previous:
            return None
        return round(((current - previous) / abs(previous)) * 100, 2)

    def _currency_data(self):
        currency = self.env.company.currency_id
        return {
            "symbol": currency.symbol or "",
            "position": currency.position or "before",
            "digits": currency.decimal_places,
        }

    def _get_summary(self, domain, domain_ui):
        Order = self.env["sale.order"]
        totals = Order.read_group(domain, ["amount_total:sum"], [])
        revenue = totals[0].get("amount_total", 0.0) if totals else 0.0

        order_count = Order.search_count(domain)
        return {
            "total_revenue": revenue,
            "total_orders": order_count,
            "average_order_value": revenue / order_count if order_count else 0.0,
            "domain": domain_ui,
        }

    def _get_monthly_revenue(self, domain, months=6):
        Order = self.env["sale.order"]
        option_domain = [("state", "in", ["draft", "sent"])]
        today = fields.Date.context_today(self)
        start_month = today.replace(day=1) - relativedelta(months=months - 1)
        month_keys = []
        month_values = {}

        for index in range(months):
            month_date = start_month + relativedelta(months=index)
            key = month_date.strftime("%Y-%m")
            month_keys.append((key, month_date.strftime("%b %Y")))
            month_values[key] = {
                "revenue": 0.0,
                "orders": 0,
                "option_revenue": 0.0,
                "option_orders": 0,
            }

        start_dt = fields.Datetime.to_string(datetime.combine(start_month, time.min))

        for value_key, count_key, order_domain in (
            ("revenue", "orders", domain),
            ("option_revenue", "option_orders", option_domain),
        ):
            orders = Order.search(order_domain + [("date_order", ">=", start_dt)])
            for order in orders:
                if not order.date_order:
                    continue
                key = fields.Datetime.to_datetime(order.date_order).strftime("%Y-%m")
                if key in month_values:
                    month_values[key][value_key] += order.amount_total
                    month_values[key][count_key] += 1

        max_revenue = max(
            [max(month_values[key]["revenue"], month_values[key]["option_revenue"]) for key, label in month_keys]
            or [0.0]
        )
        return [
            {
                "label": label,
                "revenue": month_values[key]["revenue"],
                "orders": month_values[key]["orders"],
                "percent": self._percent(month_values[key]["revenue"], max_revenue),
                "option_revenue": month_values[key]["option_revenue"],
                "option_orders": month_values[key]["option_orders"],
                "option_percent": self._percent(month_values[key]["option_revenue"], max_revenue),
            }
            for key, label in month_keys
        ]

    def _get_lost_pipeline(self, months=6):
        Order = self.env["sale.order"]
        domain = [("state", "=", "cancel")]
        today = fields.Date.context_today(self)
        start_month = today.replace(day=1) - relativedelta(months=months - 1)
        month_keys = []
        month_values = {}

        for index in range(months):
            month_date = start_month + relativedelta(months=index)
            key = month_date.strftime("%Y-%m")
            month_keys.append((key, month_date.strftime("%b %Y"), month_date))
            month_values[key] = {"revenue": 0.0, "orders": 0}

        start_dt = fields.Datetime.to_string(datetime.combine(start_month, time.min))
        orders = Order.search(domain + [("date_order", ">=", start_dt)])
        for order in orders:
            if not order.date_order:
                continue
            key = fields.Datetime.to_datetime(order.date_order).strftime("%Y-%m")
            if key in month_values:
                month_values[key]["revenue"] += order.amount_total
                month_values[key]["orders"] += 1

        max_revenue = max([month_values[key]["revenue"] for key, label, month_date in month_keys] or [0.0])
        return [
            {
                "label": label,
                "revenue": month_values[key]["revenue"],
                "orders": month_values[key]["orders"],
                "percent": self._percent(month_values[key]["revenue"], max_revenue),
                "domain": [
                    ["state", "=", "cancel"],
                    ["date_order", ">=", fields.Datetime.to_string(datetime.combine(month_date, time.min))],
                    ["date_order", "<=", fields.Datetime.to_string(datetime.combine(month_date + relativedelta(months=1, days=-1), time.max))],
                ],
            }
            for key, label, month_date in month_keys
        ]

    def _get_invoicing(self, domain, domain_ui):
        orders = self.env["sale.order"].search(domain)
        to_invoice = sum(orders.mapped("amount_to_invoice"))
        invoiced = sum(orders.mapped("amount_invoiced"))
        return {
            "to_invoice": to_invoice,
            "invoiced": invoiced,
            "to_invoice_domain": domain_ui + [["invoice_status", "=", "to invoice"]],
            "invoiced_domain": domain_ui + [["invoice_status", "in", ["invoiced", "upselling"]]],
        }

    def _get_quotation_aging(self):
        Order = self.env["sale.order"]
        orders = Order.search([("state", "in", ["draft", "sent"])])
        now = fields.Datetime.now()
        buckets = [
            {"id": "0_7", "label": _("0-7 Days"), "min_days": 0, "max_days": 7, "count": 0, "amount": 0.0},
            {"id": "8_30", "label": _("8-30 Days"), "min_days": 8, "max_days": 30, "count": 0, "amount": 0.0},
            {"id": "31_90", "label": _("31-90 Days"), "min_days": 31, "max_days": 90, "count": 0, "amount": 0.0},
            {"id": "90_plus", "label": _("90+ Days"), "min_days": 91, "max_days": False, "count": 0, "amount": 0.0},
        ]

        for order in orders:
            if not order.create_date:
                continue
            age_days = (now - order.create_date).days
            for bucket in buckets:
                if age_days >= bucket["min_days"] and (not bucket["max_days"] or age_days <= bucket["max_days"]):
                    bucket["count"] += 1
                    bucket["amount"] += order.amount_total
                    break

        total_count = sum(bucket["count"] for bucket in buckets)
        result = []
        for bucket in buckets:
            bucket_domain = [["state", "in", ["draft", "sent"]]]
            max_create = now - timedelta(days=bucket["min_days"])
            bucket_domain.append(["create_date", "<=", fields.Datetime.to_string(max_create)])
            if bucket["max_days"]:
                min_create = now - timedelta(days=bucket["max_days"])
                bucket_domain.append(["create_date", ">=", fields.Datetime.to_string(min_create)])
            result.append({
                "id": bucket["id"],
                "label": bucket["label"],
                "count": bucket["count"],
                "amount": bucket["amount"],
                "percent": self._percent(bucket["count"], total_count),
                "domain": bucket_domain,
            })
        return result

    def _get_customer_insights(self, domain):
        Order = self.env["sale.order"]
        groups = Order.read_group(domain, ["amount_total:sum"], ["partner_id"], lazy=False)
        groups = [group for group in groups if group.get("partner_id")]
        total_customers = len(groups)
        repeat_customers = sum(1 for group in groups if group.get("__count", 0) > 1)
        new_customers = max(total_customers - repeat_customers, 0)
        total_orders = sum(group.get("__count", 0) for group in groups)
        repeat_orders = sum(group.get("__count", 0) for group in groups if group.get("__count", 0) > 1)
        new_orders = max(total_orders - repeat_orders, 0)

        return {
            "total_customers": total_customers,
            "new_customers": new_customers,
            "repeat_customers": repeat_customers,
            "new_customer_percent": self._percent(new_customers, total_customers),
            "repeat_customer_percent": self._percent(repeat_customers, total_customers),
            "new_order_percent": self._percent(new_orders, total_orders),
            "repeat_order_percent": self._percent(repeat_orders, total_orders),
        }

    def _get_product_data(self, domain, date_domain_lines=None):
        date_domain_lines = [list(cond) for cond in (date_domain_lines or [])]
        Line = self.env["sale.order.line"]
        Product = self.env["product.product"]
        colors = ["#2f95ed", "#18cf93", "#ffbd45", "#ff5a66", "#8b6bd9", "#4dd4d0"]
        groups = Line.read_group(
            domain,
            ["price_total:sum", "product_uom_qty:sum"],
            ["product_id"],
            lazy=False,
        )

        category_totals = defaultdict(float)
        products = []
        for group in groups:
            product_tuple = group.get("product_id")
            if not product_tuple:
                continue
            product = Product.browse(product_tuple[0])
            revenue = group.get("price_total", 0.0)
            quantity = group.get("product_uom_qty", 0.0)
            category = product.categ_id
            category_totals[category.id or 0] += revenue
            products.append({
                "id": product.id,
                "name": product.display_name,
                "revenue": revenue,
                "quantity": quantity,
                "category": category.display_name or "Uncategorized",
                "domain": [["product_id", "=", product.id], ["order_id.state", "in", ["sale", "done"]]] + date_domain_lines,
            })

        category_total = sum(category_totals.values())
        categories = []
        for index, (category_id, revenue) in enumerate(sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:6]):
            category = self.env["product.category"].browse(category_id)
            categories.append({
                "id": category_id,
                "name": category.display_name if category_id else "Uncategorized",
                "revenue": revenue,
                "percent": self._percent(revenue, category_total),
                "color": colors[index % len(colors)],
                "domain": ([["product_id.categ_id", "=", category_id], ["order_id.state", "in", ["sale", "done"]]] if category_id else [["product_id.categ_id", "=", False], ["order_id.state", "in", ["sale", "done"]]]) + date_domain_lines,
            })

        top_revenue = sorted(products, key=lambda item: item["revenue"], reverse=True)[:5]
        max_revenue = max([item["revenue"] for item in top_revenue] or [0.0])
        for index, item in enumerate(top_revenue):
            item["percent"] = self._percent(item["revenue"], max_revenue)
            item["color"] = colors[index % len(colors)]

        top_volume = sorted(products, key=lambda item: item["quantity"], reverse=True)[:5]
        total_volume = sum(item["quantity"] for item in top_volume)
        for index, item in enumerate(top_volume):
            item["percent"] = self._percent(item["quantity"], total_volume)
            item["color"] = colors[index % len(colors)]

        return {
            "categories": categories,
            "top_revenue": top_revenue,
            "top_volume": top_volume,
        }

    def _get_salespeople(self, domain, date_domain=None):
        date_domain = [list(cond) for cond in (date_domain or [])]
        Order = self.env["sale.order"]
        colors = ["#2f95ed", "#18cf93", "#ffbd45", "#ff5a66", "#8b6bd9"]
        groups = Order.read_group(domain, ["amount_total:sum"], ["user_id"], lazy=False)
        groups = sorted(groups, key=lambda item: item.get("amount_total", 0.0), reverse=True)[:5]
        total = sum(group.get("amount_total", 0.0) for group in groups)
        return [
            {
                "id": group["user_id"][0] if group.get("user_id") else False,
                "name": group["user_id"][1] if group.get("user_id") else "Unassigned",
                "revenue": group.get("amount_total", 0.0),
                "percent": self._percent(group.get("amount_total", 0.0), total),
                "color": colors[index % len(colors)],
                "domain": ([["user_id", "=", group["user_id"][0]], ["state", "in", ["sale", "done"]]] if group.get("user_id") else [["user_id", "=", False], ["state", "in", ["sale", "done"]]]) + date_domain,
            }
            for index, group in enumerate(groups)
        ]

    def _get_top_customers(self, domain, date_domain=None):
        date_domain = [list(cond) for cond in (date_domain or [])]
        Order = self.env["sale.order"]
        groups = Order.read_group(domain, ["amount_total:sum"], ["partner_id"], lazy=False)
        groups = [group for group in groups if group.get("partner_id")]
        groups = sorted(groups, key=lambda item: item.get("amount_total", 0.0), reverse=True)[:5]
        max_revenue = max([group.get("amount_total", 0.0) for group in groups] or [0.0])
        return [
            {
                "id": group["partner_id"][0],
                "name": group["partner_id"][1],
                "revenue": group.get("amount_total", 0.0),
                "orders": group.get("__count", 0),
                "percent": self._percent(group.get("amount_total", 0.0), max_revenue),
                "domain": [["partner_id", "=", group["partner_id"][0]], ["state", "in", ["sale", "done"]]] + date_domain,
            }
            for group in groups
        ]

    def _get_best_client(self, domain, date_domain=None):
        date_domain = [list(cond) for cond in (date_domain or [])]
        Order = self.env["sale.order"]
        groups = Order.read_group(domain, ["amount_total:sum"], ["partner_id"], lazy=False)
        groups = [group for group in groups if group.get("partner_id")]
        if not groups:
            return False
        best = max(groups, key=lambda group: group.get("amount_total", 0.0))
        partner_id = best["partner_id"][0]
        return {
            "id": partner_id,
            "name": best["partner_id"][1],
            "revenue": best.get("amount_total", 0.0),
            "orders": best.get("__count", 0),
            "domain": [["partner_id", "=", partner_id], ["state", "in", ["sale", "done"]]] + date_domain,
        }

    def _get_red_client(self, date_domain=None):
        date_domain = date_domain or []
        Order = self.env["sale.order"]
        domain = [("state", "=", "cancel")] + date_domain
        groups = Order.read_group(domain, ["amount_total:sum"], ["partner_id"], lazy=False)
        groups = [group for group in groups if group.get("partner_id")]
        if not groups:
            return False
        worst = max(groups, key=lambda group: group.get("__count", 0))
        partner_id = worst["partner_id"][0]
        return {
            "id": partner_id,
            "name": worst["partner_id"][1],
            "cancelled_orders": worst.get("__count", 0),
            "cancelled_amount": worst.get("amount_total", 0.0),
            "domain": [["partner_id", "=", partner_id], ["state", "=", "cancel"]] + [list(cond) for cond in date_domain],
        }

    def _get_conversion(self, date_domain=None):
        date_domain = date_domain or []
        Order = self.env["sale.order"]
        confirmed_state_domain = [("state", "in", ["sale", "done"])] + date_domain
        total = Order.search_count(date_domain)
        confirmed = Order.search_count(confirmed_state_domain)
        return {
            "total_quotations": total,
            "confirmed_orders": confirmed,
            "conversion_rate": self._percent(confirmed, total),
            "quotations_domain": [list(cond) for cond in date_domain],
            "confirmed_domain": [list(cond) for cond in confirmed_state_domain],
        }

    def _get_geography(self, domain, date_domain=None):
        date_domain = [list(cond) for cond in (date_domain or [])]
        Order = self.env["sale.order"]
        Partner = self.env["res.partner"]
        country_totals = defaultdict(float)
        groups = Order.read_group(domain, ["amount_total:sum"], ["partner_id"], lazy=False)
        for group in groups:
            partner_tuple = group.get("partner_id")
            if not partner_tuple:
                country_totals[0] += group.get("amount_total", 0.0)
                continue
            partner = Partner.browse(partner_tuple[0])
            country = partner.country_id
            country_totals[country.id or 0] += group.get("amount_total", 0.0)

        rows = sorted(country_totals.items(), key=lambda item: item[1], reverse=True)[:5]
        max_revenue = max([revenue for country_id, revenue in rows] or [0.0])
        return [
            {
                "id": country_id,
                "name": self.env["res.country"].browse(country_id).name if country_id else "Unspecified",
                "revenue": revenue,
                "percent": self._percent(revenue, max_revenue),
                "domain": ([["partner_id.country_id", "=", country_id], ["state", "in", ["sale", "done"]]] if country_id else [["partner_id.country_id", "=", False], ["state", "in", ["sale", "done"]]]) + date_domain,
            }
            for country_id, revenue in rows
        ]

    def _get_team_achievement(self, domain, date_domain=None):
        date_domain = [list(cond) for cond in (date_domain or [])]
        Order = self.env["sale.order"]
        Team = self.env["crm.team"]
        target_field = next((field for field in ["invoiced_target", "sale_target"] if field in Team._fields), False)
        groups = Order.read_group(domain, ["amount_total:sum"], ["team_id"], lazy=False)
        groups = sorted(groups, key=lambda item: item.get("amount_total", 0.0), reverse=True)[:5]
        rows = []
        for group in groups:
            team_id = group["team_id"][0] if group.get("team_id") else False
            team = Team.browse(team_id) if team_id else Team
            actual = group.get("amount_total", 0.0)
            target = team[target_field] if target_field and team else 0.0
            rows.append({
                "id": team_id,
                "name": group["team_id"][1] if group.get("team_id") else "No Sales Team",
                "actual": actual,
                "target": target,
                "achievement": self._percent(actual, target),
                "actual_percent": 0,
                "target_percent": 0,
                "domain": ([["team_id", "=", team_id], ["state", "in", ["sale", "done"]]] if team_id else [["team_id", "=", False], ["state", "in", ["sale", "done"]]]) + date_domain,
            })

        max_value = max([max(row["actual"], row["target"]) for row in rows] or [0.0])
        for row in rows:
            row["actual_percent"] = self._percent(row["actual"], max_value)
            row["target_percent"] = self._percent(row["target"], max_value)
        return rows

    def _percent(self, value, total):
        if not total:
            return 0
        return round((float(value or 0.0) / float(total)) * 100, 2)
