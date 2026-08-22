import { io } from 'socket.io-client'
import { getCachedListResource, getCachedResource } from 'frappe-ui'

export function initSocket() {
  let socketio_port = window.socketio_port || 9000
  let host = window.location.hostname
  let siteName = window.site_name
  let port = window.location.port ? `:${socketio_port}` : ''
  let protocol = port ? 'http' : 'https'
  let url = `${protocol}://${host}${port}/${siteName}`

  let socket = io(url, {
    withCredentials: true,
    reconnectionAttempts: 5,
    // Hostyo customization: force WebSocket-only, skipping the default
    // polling-first handshake entirely.
    //
    // Root cause traced via frappe/frappe's realtime/middlewares/authenticate.js:
    // it rejects the connection with "Invalid origin" whenever
    // get_hostname(socket.request.headers.host) != get_hostname(socket.request.headers.origin).
    // That check runs when Socket.IO processes the client's namespace-CONNECT
    // packet (protocol packet "40") - which, with the default transport
    // order, is sent as a separate POST over the *polling* transport,
    // before any WebSocket upgrade is even attempted. socket.request at
    // that point is Engine.IO's current request for the session, i.e. that
    // POST - not the original GET handshake, and not the later WS upgrade.
    //
    // Captured browser Network-tab evidence on this deployment:
    //   - the initial polling GET handshake: no Origin header at all
    //     (unremarkable on its own - browsers don't send Origin on
    //     same-origin GETs either way)
    //   - the WebSocket upgrade request: Origin present and correctly
    //     matching Host (crm.hostyo.com both sides) - this succeeds (101)
    // The polling-phase CONNECT POST's own headers were never directly
    // captured, but get_hostname(undefined) returns undefined (confirmed
    // in frappe/frappe's realtime/utils.js), which can never equal
    // get_hostname(host) - so a missing Origin on that specific POST alone
    // is sufficient to reproduce "Invalid origin" exactly as observed:
    // immediately, consistently, before WS upgrade ever runs.
    //
    // Forcing websocket-only means the CONNECT packet rides the same
    // upgrade request already confirmed to carry a matching Origin -
    // sidestepping the polling-phase request (and whatever about it is
    // dropping Origin) entirely, without needing a Caddy-side fix.
    //
    // Trade-off: no polling fallback. A client whose network blocks raw
    // WebSocket upgrades (rare on ordinary networks; some restrictive
    // corporate proxies still do) would get no realtime connection at all,
    // versus a working-but-less-efficient polling connection under the
    // default transport order. Given this deployment has already proven
    // full WebSocket support (the captured 101 upgrade) and this is an
    // internal tool on ordinary business networks, that trade-off is low
    // risk here. Revisit if agents ever report realtime features silently
    // not working from a specific network.
    transports: ['websocket'],
  })
  socket.on('refetch_resource', (data) => {
    if (data.cache_key) {
      let resource =
        getCachedResource(data.cache_key) ||
        getCachedListResource(data.cache_key)
      if (resource) {
        resource.reload()
      }
    }
  })
  return socket
}
