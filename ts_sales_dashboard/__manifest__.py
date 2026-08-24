# -*- coding: utf-8 -*-
{
    "name": "Advanced Sales Dashboard",
    "summary": "Executive sales dashboard with revenue, customers, products, geography, and team KPIs. Works on Odoo Community and Enterprise.",
    "version": "19.0.2.0.0",
    "category": "Sales",
    "author": "Mudassir Amin, Inovado D.o.o., Mirsad Selimovic, Techman Solutions",
    "website": "https://inovado.ba, https://techman.qa, https://www.mudassir.it.com",
    "license": "LGPL-3",
    "depends": ["sale"],
    "data": [
        "views/sales_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ts_sales_dashboard/static/src/js/sales_dashboard_action.js",
            "ts_sales_dashboard/static/src/js/control_panel_dashboard_button.js",
            "ts_sales_dashboard/static/src/xml/sales_dashboard_templates.xml",
            "ts_sales_dashboard/static/src/xml/control_panel_dashboard_button.xml",
            "ts_sales_dashboard/static/src/css/sales_dashboard.css",
        ],
    },
    "images": [
        "static/description/banner.png",
        "static/description/cover.png",
        "static/description/dashboard_hero.png",
        "static/description/dashboard_date_filter.png",
        "static/description/dashboard_comparison.png",
        "static/description/dashboard_pipeline_aging.png",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
