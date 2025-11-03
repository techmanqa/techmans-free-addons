{
    'name': 'Product Markup Calculation',
    'version': '18.0.1.0.0',
    'category': 'Product',
    'summary': 'Adds two custom fields to the product model, with one calculated field.',
    'description': """
        This module adds two custom fields to the product.template model in Odoo 18:
        - Mark Up in % (selection)
        - Total Mark Up (automatically calculated)
    """,
    'author': 'Mirsad Selimovic @ Techman Solutions',
    "maintainer": "Techman Solutions W.L.L.",
    'support': 'odoo@techman.qa',
    'website': 'https://www.techman.qa',
    'license': 'LGPL-3',
    'depends': ['product'],
    'data': [
        'views/product_template_view.xml',
    ],
    'image': 'static/description/icon.png',
    'installable': True,
    'application': False,
    'auto_install': False,
    
    # Odoo App Store - Free app info
    'price': 0.0,
    'currency': 'USD',

}
