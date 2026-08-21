from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class ClientHubPortal(CustomerPortal):

    def _get_assets_domain(self):
        partner = request.env.user.partner_id
        return [('partner_id', 'child_of', partner.commercial_partner_id.id)]

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'asset_count' in counters:
            values['asset_count'] = (
                request.env['partner.asset'].search_count(self._get_assets_domain())
                if request.env['partner.asset'].has_access('read') else 0
            )
        return values

    @http.route(['/my/assets', '/my/assets/page/<int:page>'], type='http',
                auth='user', website=True)
    def portal_my_assets(self, page=1, **kw):
        Asset = request.env['partner.asset']
        domain = self._get_assets_domain()
        total = Asset.search_count(domain)
        pager = portal_pager(url='/my/assets', total=total, page=page, step=20)
        assets = Asset.search(domain, order='end_date asc, id desc',
                              limit=20, offset=pager['offset'])
        return request.render('ts_partner_app.portal_my_assets', {
            'assets': assets,
            'pager': pager,
            'page_name': 'assets',
        })

    @http.route('/my/assets/<int:asset_id>', type='http', auth='user', website=True)
    def portal_asset_detail(self, asset_id, renewal_requested=False, **kw):
        asset = request.env['partner.asset'].search(
            [('id', '=', asset_id)] + self._get_assets_domain(), limit=1)
        if not asset:
            return request.redirect('/my/assets')
        return request.render('ts_partner_app.portal_asset_detail', {
            'asset': asset,
            'page_name': 'assets',
            'renewal_requested': renewal_requested,
        })

    @http.route('/my/assets/<int:asset_id>/request_renewal', type='http',
                auth='user', methods=['POST'], website=True, csrf=True)
    def portal_asset_request_renewal(self, asset_id, message=None, **kw):
        asset = request.env['partner.asset'].search(
            [('id', '=', asset_id)] + self._get_assets_domain(), limit=1)
        if asset:
            # sudo: the portal user is read-only on assets; posting the request
            # (chatter message + activity for the responsible user) needs write.
            asset.sudo()._portal_request_renewal(message=(message or '').strip()[:1000])
        return request.redirect('/my/assets/%s?renewal_requested=1' % asset_id)
