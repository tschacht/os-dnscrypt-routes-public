{#
 # Services > DNSCrypt-Proxy > Anonymized Routing (plan section 5, Figure 5).
 # Standard building blocks: service widget, base_form, UIBootgrid, base_dialog; the route matrix is a plain table.
 # API: /api/dnscryptroutes/... (C-03). Status: C-02 + pending. Test result: C-04. Catalog: C-05.
 #}

<style>
    #dr_strip .dr-cell-label { font-size: 11px; text-transform: uppercase; }
    #dr_strip td { width: 25%; }
    #dr_matrix th.dr-relay, #dr_matrix td.dr-relay { text-align: center; white-space: nowrap; }
    #dr_matrix td.dr-used { background-color: #dff0d8; }
    #dr_matrix td.dr-locked { color: #999; background-color: #f5f5f5; }
    #dr_matrix td.dr-error, #dr_matrix th.dr-error { background-color: #f2dede; }
    #dr_matrix tr.dr-row-msg td { border-top: 0; padding-top: 0; }
    .dr-legend span { display: inline-block; margin-right: 1.5em; }
    .dr-legend i.dr-swatch { display: inline-block; width: 1em; height: 1em; vertical-align: middle; border: 1px solid #ccc; }
    .dr-section-head { padding: 10px 15px 0 15px; }
</style>

{# ---- status strip (R-10) ---- #}
<div class="content-box __mb" id="dr_strip">
    <table class="table table-condensed" style="margin-bottom: 0;">
        <tr>
            <td><span class="text-muted dr-cell-label">{{ lang._('Policy') }}</span><br/><b id="dr_policy">…</b></td>
            <td><span class="text-muted dr-cell-label">{{ lang._('Live servers (log)') }}</span><br/><b id="dr_live">…</b></td>
            <td><span class="text-muted dr-cell-label">{{ lang._('Last applied') }}</span><br/><b id="dr_applied">…</b></td>
            <td><span class="text-muted dr-cell-label">{{ lang._('Pending') }}</span><br/><b id="dr_pending">…</b></td>
        </tr>
    </table>
    <div id="dr_alerts" style="padding: 0 10px;"></div>
    <div id="dr_notices" style="padding: 0 10px;"></div>
</div>

{# ---- General ---- #}
<div class="content-box __mb">
    <h2 class="dr-section-head">{{ lang._('General') }}</h2>
    {{ partial("layout_partials/base_form",['fields':generalForm,'id':'frm_general']) }}
</div>

{# ---- Relays (bootgrid, edit dialog dialogRelay) ---- #}
<div class="content-box __mb">
    <h2 class="dr-section-head">{{ lang._('Relays') }} <small>{{ lang._('from the signed relays.md catalog') }}</small></h2>
    <table id="grid-relays" class="table table-condensed table-hover table-striped" data-editDialog="dialogRelay">
        <thead>
            <tr>
                <th data-column-id="uuid" data-type="string" data-identifier="true" data-visible="false">{{ lang._('ID') }}</th>
                <th data-column-id="name" data-type="string" data-formatter="relayname">{{ lang._('Relay') }}</th>
                <th data-column-id="operator" data-type="string">{{ lang._('Operator') }}</th>
                <th data-column-id="commands" data-width="7em" data-formatter="commands" data-sortable="false">{{ lang._('Commands') }}</th>
            </tr>
        </thead>
        <tbody>
        </tbody>
        <tfoot>
            <tr>
                <td></td>
                <td>
                    <button data-action="add" type="button" class="btn btn-xs btn-primary"><span class="fa fa-fw fa-plus"></span></button>
                </td>
            </tr>
        </tfoot>
    </table>
</div>

{# ---- Resolvers and routes (route matrix) ---- #}
<div class="content-box __mb">
    <h2 class="dr-section-head">{{ lang._('Resolvers and routes') }}
        <small>{{ lang._('Tick the relays each resolver may use. A resolver can never use a relay run by its own operator.') }}</small>
    </h2>
    <div class="table-responsive">
        <table class="table table-condensed table-striped" id="dr_matrix">
            <thead></thead>
            <tbody></tbody>
        </table>
    </div>
    <div style="padding: 0 10px;">
        <div id="dr_matrix_warnings"></div>
        <button type="button" class="btn btn-xs btn-primary" id="dr_add_resolver">
            <span class="fa fa-fw fa-plus"></span> {{ lang._('Add resolver') }}
        </button>
        <small class="text-muted">{{ lang._('searchable, from the signed public-resolvers.md catalog') }}</small>
        <p class="dr-legend text-muted" style="margin-top: 10px;">
            <span><i class="dr-swatch" style="background-color: #dff0d8;"></i> {{ lang._('route used') }}</span>
            <span><i class="dr-swatch"></i> {{ lang._('allowed, unused') }}</span>
            <span><i class="fa fa-lock"></i> {{ lang._('blocked: same operator (or the same server)') }}</span>
        </p>
    </div>
</div>

{# ---- actions ---- #}
<div class="content-box __mb" style="padding: 10px;">
    <div id="dr_messages"></div>
    <div id="dr_warnings"></div>
    <button class="btn btn-primary" id="dr_save_apply" type="button"><b>{{ lang._('Save & Apply') }}</b> <i class="dr-progress"></i></button>
    <button class="btn btn-default" id="dr_save_test" type="button"><b>{{ lang._('Save & Test') }}</b> <i class="dr-progress"></i></button>
    <p class="text-muted" style="margin-top: 10px; margin-bottom: 0;">
        {{ lang._('Apply restarts dnscrypt-proxy (about 60 s). Test is optional: it runs a temporary copy on 127.0.0.1:5354 and leaves live DNS alone.') }}
        {{ lang._('The test sends real DNS queries to the selected resolvers through the selected relays.') }}
    </p>
</div>

{# ---- test result panel (C-04), shown only once a test has run ---- #}
<div class="content-box __mb" id="dr_testpanel" style="display: none; padding: 10px;">
    <p id="dr_test_head"></p>
    <div id="dr_test_note"></div>
    <div id="dr_test_error"></div>
    <div class="table-responsive">
        <table class="table table-condensed table-striped" id="dr_test_table">
            <thead>
                <tr>
                    <th>{{ lang._('Resolver') }}</th>
                    <th>{{ lang._('Route used in this test') }}</th>
                    <th>{{ lang._('Certificate') }}</th>
                    <th>{{ lang._('RTT') }}</th>
                    <th>{{ lang._('Result') }}</th>
                </tr>
            </thead>
            <tbody></tbody>
        </table>
    </div>
    <p class="text-muted small" id="dr_test_relays" style="display: none;">
        {{ lang._('At each start dnscrypt-proxy uses one relay per resolver, chosen at random. Relays not shown were not tested in this run; Save & Test again to cover others.') }}
    </p>
    <p class="text-muted" id="dr_test_queries"></p>
    <p class="text-muted small" id="dr_test_unknown" style="display: none;">
        {{ lang._('unknown: dnscrypt-proxy never used this resolver. It is not in the cached signed resolver list, or it is not a DNSCrypt server and was dropped by the forced protocol filters (DoH and ODoH are off while anonymized routing is enabled).') }}
    </p>
    <button class="btn btn-primary" id="dr_test_apply" type="button" style="display: none;"><b>{{ lang._('Apply') }}</b> <i class="dr-progress"></i></button>
</div>

{{ partial("layout_partials/base_dialog",['fields':formDialogRelay,'id':'dialogRelay','label':lang._('Relay')]) }}
{{ partial("layout_partials/base_dialog",['fields':formDialogResolver,'id':'dialogResolver','label':lang._('Resolver')]) }}

<script>
$(document).ready(function () {
    const API = '/api/dnscryptroutes/';
    const T = {
        applied: "{{ lang._('Applied') }}",
        notApplied: "{{ lang._('Not applied (DNS stopped)') }}",
        refused: "{{ lang._('Refused (DNS stopped)') }}",
        off: "{{ lang._('Off') }}",
        baseOff: "{{ lang._('Off: DNSCrypt-Proxy is disabled') }}",
        savedNotApplied: "{{ lang._('Saved, not applied') }}",
        unsaved: "{{ lang._('Unsaved changes') }}",
        none: "{{ lang._('None') }}",
        never: "{{ lang._('Never') }}",
        invariant: "{{ lang._('Invariant violated: the generated configuration breaks the relay-only rule, so it was replaced by a fail-closed one and DNS is stopped. Correct the routes and Save & Apply, or untick Enable anonymized routing and Save & Apply.') }}",
        notAppliedAlert: "{{ lang._('Override not applied: the stock os-dnscrypt-proxy template no longer has the lines this plugin patches, so DNS is stopped (fail closed). Untick Enable anonymized routing and Save & Apply, then update os-dnscrypt-routes.') }}",
        direct: "{{ lang._('Direct connection detected: dnscrypt-proxy uses these servers without a relay:') }}",
        skipOff: "{{ lang._('Relay-only routing not guaranteed: skip incompatible is off') }}",
        shadowed: "{{ lang._('The manual 90-eu override is shadowed: the running configuration was generated with anonymized routing. Untick Enable anonymized routing and Save & Apply to use the override again.') }}",
        leftover: "{{ lang._('A manual dnscrypt-proxy-eu.toml template is present without its 90-eu.TARGET mapping. It is a leftover file and has no effect.') }}",
        sameOperator: "{{ lang._('same operator') }}",
        sameServer: "{{ lang._('same server') }}",
        lockedTitle: "{{ lang._('Locked: a resolver can never use a relay run by its own operator (or the relay of the same server).') }}",
        lockedTicked: "{{ lang._('not allowed, untick it') }}",
        singleRelay: "{{ lang._('has a single relay. It is allowed but has no failover.') }}",
        noRelay: "{{ lang._('is enabled but has no relay. Tick at least one relay, or untick On.') }}",
        noRelayHint: "{{ lang._('A resolver with no relay cannot be saved while anonymized routing is enabled.') }}",
        notSaved: "{{ lang._('Not saved:') }}",
        notDeleted: "{{ lang._('Not deleted') }}",
        failedGeneric: "{{ lang._('The request failed. Reload the page and try again.') }}",
        applyFailed: "{{ lang._('Apply failed:') }}",
        appliedOk: "{{ lang._('Applied: dnscrypt-proxy was restarted with the saved settings.') }}",
        waitingLive: "{{ lang._('Restarting dnscrypt-proxy: waiting until its servers are loaded (about 60 s).') }}",
        stockLists: "{{ lang._('The stock Server list / Relay list on the Configuration page is not empty. It is overridden while anonymized routing is enabled, as are the stock DNSCrypt/DoH/ODoH protocol settings.') }}",
        notRunning: "{{ lang._('dnscrypt-proxy is not running after the restart. See the alerts at the top of the page, or Services → DNSCrypt-Proxy → Log / General.') }}",
        noLiveServers: "{{ lang._('dnscrypt-proxy was restarted, but its log shows no live servers after 90 s. Check Log / General.') }}",
        close: "{{ lang._('Close') }}",
        noCatalog: "{{ lang._('Catalog unavailable. Start DNSCrypt-Proxy once so it downloads the signed resolver list.') }}",
        notDnscrypt: "{{ lang._('not DNSCrypt') }}",
        testRunning: "{{ lang._('Test running: candidate configuration in a temporary instance on 127.0.0.1:5354 (at most 90 s)') }}",
        testAlready: "{{ lang._('A test was already running; its result is shown below.') }}",
        testNotStarted: "{{ lang._('The test could not start:') }}",
        testRunningNeutral: "{{ lang._('Test running in a temporary instance on 127.0.0.1:5354 (at most 90 s)') }}",
        lastTest: "{{ lang._('Last test: candidate configuration') }}",
        lastTestNeutral: "{{ lang._('Last test') }}",
        lastTestOff: "{{ lang._('Last test: configuration without anonymized routing') }}",
        testRoutingOff: "{{ lang._('Anonymized routing is off: this tested the configuration dnscrypt-proxy uses without it (stock or the manual override), not the routes above. Tick Enable anonymized routing and Save & Test to test them.') }}",
        testOutdated: "{{ lang._('Settings changed since this test: it does not cover the saved settings. Save & Test again before applying from here.') }}",
        stopped: "{{ lang._('Stopped') }}",
        utc: "{{ lang._('UTC') }}",
        instanceStopped: "{{ lang._('temporary instance stopped') }}",
        testFailed: "{{ lang._('Test failed:') }}",
        errTimeout: "{{ lang._('timeout, the 90 s limit was reached') }}",
        errCheck: "{{ lang._('the candidate configuration was refused') }}",
        errCrashed: "{{ lang._('the test stopped unexpectedly') }}",
        queriesVia: "{{ lang._('Test queries via 127.0.0.1:5354:') }}",
        via: "{{ lang._('via') }}",
        directRoute: "{{ lang._('none: queried directly') }}",
        pass: "{{ lang._('pass') }}",
        failDirect: "{{ lang._('direct query') }}",
        failProto: "{{ lang._('not DNSCrypt') }}",
        failNoAnswer: "{{ lang._('no answer') }}",
        failUnused: "{{ lang._('not used') }}",
        failError: "{{ lang._('error') }}",
        failNoRoute: "{{ lang._('no relay route') }}",
        on: "{{ lang._('On') }}",
        resolver: "{{ lang._('Resolver') }}",
        operator: "{{ lang._('Operator') }}",
        routes: "{{ lang._('Routes') }}",
        edit: "{{ lang._('Edit') }}",
        del: "{{ lang._('Delete') }}",
        ecsWarning: "{{ lang._('Privacy: the subnet is sent to the resolvers with your queries. The preset 146.70.82.0/24 is synthetic; never use your WAN subnet, it may reveal your real network.') }}"
    };
    // lang._() output is HTML-escaped; keep plain text here and escape once where HTML is built
    $.each(T, function (key, value) {
        T[key] = htmlDecode(value);
    });

    let catalog = {available: false, resolvers: [], relays: []};
    let model = {enabled: '0', skip: '1', relays: [], resolvers: []};  // last loaded saved state
    let edits = {};           // resolver uuid -> {enabled, relays: [relay uuids]}: unsaved matrix changes
    let formDirty = false;    // unsaved changes in the General form
    let rowErrors = {};       // set errors on resolver rows: uuid -> {field: message}
    let relayErrors = {};     // set errors on relays: uuid -> message
    let lastStatus = null;
    let stockListsInUse = false;  // stock "Server list"/"Relay list" not empty: page load (stock API) and write warnings
    let testTimer = null;
    let testGen = 0;              // current pollTest chain
    let modelLoaded = false;      // settings/get read at least once (model.enabled is the saved state)
    let lastTest = null;          // last testStatus response, re-rendered when the saved state changes
    let changedSinceTest = false; // a write on this page changed the saved settings after the shown test started
    let sessionRun = false;       // the shown test was started by Save & Test on this page (else: neutral labels)

    function esc(value) {
        return $('<div/>').text(value === undefined || value === null ? '' : String(value)).html();
    }
    // Core HTML-escapes < > & in every JSON response (Mvc/Response::send): decode API data once where it is read,
    // escape once (esc) where HTML is built.
    function decodeAll(value) {
        if (typeof value === 'string') {
            return value.indexOf('&') >= 0 ? htmlDecode(value) : value;
        }
        if (Array.isArray(value)) {
            return value.map(decodeAll);
        }
        if (value && typeof value === 'object') {
            const out = {};
            $.each(value, function (key, item) { out[key] = decodeAll(item); });
            return out;
        }
        return value;
    }
    function apiGet(path, callback) {
        return ajaxGet(API + path, {}, function (data, status) { callback(decodeAll(data), status); });
    }
    function apiPost(path, data, callback) {
        return ajaxCall(API + path, data, function (resp, status) { callback(decodeAll(resp), status); });
    }
    function byId(id) {
        return $(document.getElementById(id));
    }
    function norm(value) {
        return String(value === undefined || value === null ? '' : value).trim().toLowerCase();
    }
    // backend times are ISO-8601 UTC ("...Z"); shown as "YYYY-MM-DD HH:MM UTC"
    function fmtTime(value) {
        if (!value) {
            return '';
        }
        const text = String(value);
        return text.replace('T', ' ').substring(0, 16) + (/Z$/.test(text) ? ' ' + T.utc : '');
    }
    function alertBox(type, html) {
        return '<div class="alert alert-' + type + '" style="margin: 10px 0;">' + html + '</div>';
    }
    function msgList(messages) {
        return messages.map(function (m) { return esc(m); }).join('<br/>');
    }
    function busy($btn, on) {
        $('#dr_save_apply, #dr_save_test, #dr_test_apply').prop('disabled', on);
        if ($btn) {
            $btn.find('.dr-progress').toggleClass('fa fa-spinner fa-pulse', on);
        }
    }
    function catalogEntry(list, name) {
        return (catalog[list] || []).find(function (e) { return e.name === name; });
    }
    function locationOf(list, name) {
        const entry = catalogEntry(list, name);
        return entry && entry.location ? String(entry.location).toUpperCase() : '';
    }

    /* ------------------------------------------------------------ model data (settings/get) */

    function readModel(data) {
        const root = (data && data.dnscryptroutes) || {};
        const general = root.general || {};
        const relays = [];
        $.each((root.relays || {}).relay || {}, function (uuid, r) {
            relays.push({uuid: uuid, name: r.name, operator: r.operator});
        });
        relays.sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
        const resolvers = [];
        $.each((root.resolvers || {}).resolver || {}, function (uuid, r) {
            const selected = [];
            $.each(r.relays || {}, function (relayUuid, opt) {
                if (String(opt.selected) !== '0') {
                    selected.push(relayUuid);
                }
            });
            resolvers.push({uuid: uuid, enabled: String(r.enabled), name: r.name, operator: r.operator, relays: selected});
        });
        return {enabled: String(general.enabled), skip: String(general.skipIncompatible), relays: relays, resolvers: resolvers};
    }

    function reloadModel() {
        return apiGet('settings/get', function (data, status) {
            if (status === 'success') {
                setModel(readModel(data));
            }
        });
    }

    function setModel(next) {
        model = next;
        modelLoaded = true;
        const resolverIds = model.resolvers.map(function (r) { return r.uuid; });
        const relayIds = model.relays.map(function (r) { return r.uuid; });
        // keep unsaved ticks of rows that still exist, drop references to deleted relays
        $.each(Object.keys(edits), function (i, uuid) {
            if (resolverIds.indexOf(uuid) < 0) {
                delete edits[uuid];
            } else {
                edits[uuid].relays = edits[uuid].relays.filter(function (r) { return relayIds.indexOf(r) >= 0; });
            }
        });
        renderMatrix();
        renderStatus();
        if (lastTest) {
            renderTest(lastTest);
        }
    }

    function findResolver(uuid) {
        return model.resolvers.find(function (r) { return r.uuid === uuid; });
    }
    function findRelay(uuid) {
        return model.relays.find(function (r) { return r.uuid === uuid; });
    }
    function rowState(resolver) {
        return edits[resolver.uuid] || {enabled: resolver.enabled, relays: resolver.relays};
    }
    function editableState(resolver) {
        if (!edits[resolver.uuid]) {
            edits[resolver.uuid] = {enabled: resolver.enabled, relays: resolver.relays.slice()};
        }
        return edits[resolver.uuid];
    }
    // drop an unsaved row edit that equals the saved state again (tick then untick)
    function pruneEdit(resolver) {
        const edit = edits[resolver.uuid];
        if (edit && edit.enabled === resolver.enabled && edit.relays.length === resolver.relays.length &&
                edit.relays.every(function (r) { return resolver.relays.indexOf(r) >= 0; })) {
            delete edits[resolver.uuid];
        }
    }
    function isDirty() {
        return formDirty || Object.keys(edits).length > 0;
    }

    /* ------------------------------------------------------------ route matrix */

    // Locked cell: the relay is run by the resolver's operator, or it is the resolver's own relay (anon-<name>).
    function lockReason(resolver, relay) {
        if (norm(relay.operator) !== '' && norm(relay.operator) === norm(resolver.operator)) {
            return T.sameOperator;
        }
        if (norm(relay.name) === 'anon-' + norm(resolver.name)) {
            return T.sameServer;
        }
        return '';
    }

    function renderMatrix() {
        const relays = model.relays;
        const columns = 5 + relays.length;
        let head = '<tr><th style="width: 3em;">' + esc(T.on) + '</th><th>' + esc(T.resolver) + '</th><th>' + esc(T.operator) + '</th>';
        relays.forEach(function (relay) {
            const err = relayErrors[relay.uuid] ? ' dr-error' : '';
            head += '<th class="dr-relay' + err + '">' + esc(relay.name) + '<br/><small class="text-muted">' + esc(relay.operator) + '</small></th>';
        });
        head += '<th>' + esc(T.routes) + '</th><th style="width: 6em;"></th></tr>';
        $('#dr_matrix > thead').html(head);

        let body = '';
        let warnings = [];
        model.resolvers.forEach(function (resolver) {
            const state = rowState(resolver);
            const errors = rowErrors[resolver.uuid] || {};
            const enabled = state.enabled === '1';
            const count = state.relays.length;
            const hasErrors = Object.keys(errors).length > 0;
            body += '<tr data-uuid="' + esc(resolver.uuid) + '">';
            body += '<td class="' + (errors.enabled ? 'dr-error' : '') + '"><input type="checkbox" class="dr-on" data-res="' +
                esc(resolver.uuid) + '"' + (enabled ? ' checked="checked"' : '') + '/></td>';
            const loc = locationOf('resolvers', resolver.name);
            body += '<td class="' + (hasErrors ? 'dr-error' : '') + '">' + (hasErrors ? '<i class="fa fa-times-circle text-danger"></i> ' : '') + esc(resolver.name) +
                (loc ? ' <small class="text-muted">' + esc(loc) + '</small>' : '') + '</td>';
            body += '<td class="' + (errors.operator ? 'dr-error' : '') + '">' + esc(resolver.operator) + '</td>';
            relays.forEach(function (relay) {
                const reason = lockReason(resolver, relay);
                const ticked = state.relays.indexOf(relay.uuid) >= 0;
                const data = ' data-res="' + esc(resolver.uuid) + '" data-rel="' + esc(relay.uuid) + '"';
                if (reason && !ticked) {
                    body += '<td class="dr-relay dr-locked" title="' + esc(T.lockedTitle) + '"><i class="fa fa-lock"></i> <small>' + esc(reason) + '</small></td>';
                } else if (reason) {
                    // saved before the operators changed: may only be unticked
                    body += '<td class="dr-relay dr-error" title="' + esc(T.lockedTitle) + '"><input type="checkbox" class="dr-cell" checked="checked"' + data +
                        '/> <i class="fa fa-lock"></i> <small>' + esc(reason) + ', ' + esc(T.lockedTicked) + '</small></td>';
                } else {
                    const err = (errors.relays && ticked && relayErrors[relay.uuid]) ? ' dr-error' : '';
                    body += '<td class="dr-relay' + (ticked ? ' dr-used' : '') + err + '"><input type="checkbox" class="dr-cell"' +
                        (ticked ? ' checked="checked"' : '') + data + '/></td>';
                }
            });
            let countHtml = String(count);
            if (enabled && count === 1) {
                countHtml += ' <i class="fa fa-exclamation-triangle text-warning"></i>';
                warnings.push('<i class="fa fa-exclamation-triangle text-warning"></i> ' + esc(resolver.name) + ' ' + esc(T.singleRelay));
            } else if (enabled && count === 0) {
                countHtml = '<span class="text-danger">0 <i class="fa fa-times-circle"></i></span>';
                warnings.push('<span class="text-danger"><i class="fa fa-times-circle"></i> ' + esc(resolver.name) + ' ' + esc(T.noRelay) + '</span>');
            }
            body += '<td class="dr-count' + (errors.relays ? ' dr-error' : '') + '">' + countHtml + '</td>';
            body += '<td class="text-nowrap">' +
                '<button type="button" class="btn btn-xs btn-default dr-edit" title="' + esc(T.edit) + '" data-res="' + esc(resolver.uuid) + '"><span class="fa fa-fw fa-pencil"></span></button> ' +
                '<button type="button" class="btn btn-xs btn-default dr-del" title="' + esc(T.del) + '" data-res="' + esc(resolver.uuid) + '"><span class="fa fa-fw fa-trash-o"></span></button></td>';
            body += '</tr>';
            const messages = Object.keys(errors).map(function (field) { return errors[field]; });
            if (messages.length) {
                body += '<tr class="dr-row-msg"><td colspan="' + columns + '" class="text-danger"><small>' + msgList(messages) + '</small></td></tr>';
            }
        });
        $('#dr_matrix > tbody').html(body);
        if (warnings.length) {
            warnings.push('<span class="text-muted">' + esc(T.noRelayHint) + '</span>');
        }
        $('#dr_matrix_warnings').html(warnings.length ? '<p>' + warnings.join('<br/>') + '</p>' : '');
    }

    // A tick in the matrix. The UI refuses to tick a locked cell (lockReason); unticking is always possible.
    function toggleRoute(resolverUuid, relayUuid, checked) {
        const resolver = findResolver(resolverUuid);
        const relay = findRelay(relayUuid);
        if (!resolver || !relay) {
            return;
        }
        const state = editableState(resolver);
        if (checked) {
            if (lockReason(resolver, relay) !== '') {
                pruneEdit(resolver);
                renderMatrix();
                return;
            }
            if (state.relays.indexOf(relayUuid) < 0) {
                state.relays.push(relayUuid);
            }
        } else {
            state.relays = state.relays.filter(function (r) { return r !== relayUuid; });
        }
        pruneEdit(resolver);
        renderMatrix();
        renderStatus();
    }

    $('#dr_matrix').on('change', 'input.dr-cell', function () {
        toggleRoute(String($(this).data('res')), String($(this).data('rel')), $(this).is(':checked'));
    });
    $('#dr_matrix').on('change', 'input.dr-on', function () {
        const resolver = findResolver(String($(this).data('res')));
        if (resolver) {
            editableState(resolver).enabled = $(this).is(':checked') ? '1' : '0';
            pruneEdit(resolver);
            renderMatrix();
            renderStatus();
        }
    });
    $('#dr_matrix').on('click', 'button.dr-edit', function () {
        openDialog('resolver', String($(this).data('res')));
    });
    $('#dr_matrix').on('click', 'button.dr-del', function () {
        deleteItem('resolver', String($(this).data('res')));
    });
    $('#dr_add_resolver').click(function () {
        openDialog('resolver', null);
    });

    /* ------------------------------------------------------------ set errors -> form, rows and cells */

    // C-03 paths: dnscryptroutes.general.<f>, dnscryptroutes.relays.relay.<uuid>.<f>, dnscryptroutes.resolvers.resolver.<uuid>.<f>
    function mapSetErrors(validations) {
        const general = {};
        const messages = [];
        rowErrors = {};
        relayErrors = {};
        $.each(validations || {}, function (path, message) {
            messages.push(message);
            let m = /^dnscryptroutes\.resolvers\.resolver\.([^.]+)\.([A-Za-z]+)$/.exec(path);
            if (m) {
                rowErrors[m[1]] = rowErrors[m[1]] || {};
                rowErrors[m[1]][m[2]] = message;
                return;
            }
            m = /^dnscryptroutes\.relays\.relay\.([^.]+)\.([A-Za-z]+)$/.exec(path);
            if (m) {
                relayErrors[m[1]] = message;
                return;
            }
            if (/^dnscryptroutes\.general\./.test(path)) {
                general[path] = message;
            }
        });
        handleFormValidation('frm_general', general);
        renderMatrix();
        return messages;
    }

    function clearSetErrors() {
        rowErrors = {};
        relayErrors = {};
        handleFormValidation('frm_general', {});
        $('#dr_messages').empty();
    }

    function showMessages(type, messages) {
        $('#dr_messages').html(messages.length ? alertBox(type, msgList(messages)) : '');
    }

    // warnings of a successful write (R-07). Single-relay and skip-incompatible warnings are shown live elsewhere,
    // the stock-lists warning goes to the notices of the status strip.
    function showWarnings(warnings) {
        const shown = (warnings || []).filter(function (w) {
            return !/\.relays$/.test(w.path) && !/\.skipIncompatible$/.test(w.path);
        });
        // general.enabled carries only the stock-lists warning (R-07); it is shown as a strip notice
        stockListsInUse = shown.some(function (w) { return /\.general\.enabled$/.test(w.path); });
        const html = shown.filter(function (w) { return !/\.general\.enabled$/.test(w.path); }).map(function (w) {
            return '<i class="fa fa-exclamation-triangle text-warning"></i> ' + esc(w.message);
        });
        $('#dr_warnings').html(html.length ? alertBox('warning', html.join('<br/>')) : '');
        renderStatus();
    }

    /* ------------------------------------------------------------ save, apply, test */

    // settings/set with the General form plus enabled/relays of every matrix row (C-03)
    function saveAll() {
        const dfd = $.Deferred();
        const data = getFormData('frm_general');
        const rows = {};
        model.resolvers.forEach(function (resolver) {
            const state = rowState(resolver);
            rows[resolver.uuid] = {enabled: state.enabled, relays: state.relays.join(',')};
        });
        data.dnscryptroutes.resolvers = {resolver: rows};
        const changes = isDirty();
        clearSetErrors();
        apiPost('settings/set', data, function (resp, status) {
            if (status === 'success' && resp && resp.result === 'saved') {
                if (changes) {
                    changedSinceTest = true;
                }
                edits = {};
                formDirty = false;
                showWarnings(resp.warnings);
                reloadModel().always(function () {
                    loadStatus();
                    dfd.resolve(resp);
                });
            } else {
                const messages = mapSetErrors(resp && resp.validations);
                showMessages('danger', [T.notSaved].concat(messages.length ? messages : [T.failedGeneric]));
                dfd.reject(resp);
            }
        });
        return dfd.promise();
    }

    function apply($btn) {
        busy($btn, true);
        apiPost('service/reconfigure', {}, function (resp, status) {
            updateServiceControlUI('dnscryptroutes');
            if (status === 'success' && resp && resp.status === 'ok') {
                showMessages('info', [T.waitingLive]);
                waitForLiveServers($btn, Date.now() + 90000, true);
            } else {
                busy($btn, false);
                let messages = [];
                if (resp && resp.validations) {
                    messages = mapSetErrors(resp.validations);
                }
                if (resp && resp.status_msg) {
                    messages.push(resp.status_msg);
                }
                showMessages('danger', [T.applyFailed].concat(messages.length ? messages : [T.failedGeneric]));
                loadStatus();
            }
        });
    }

    // after a restart the servers load for up to about 60 s: keep the spinner and re-read the status every 3 s
    // until the log reports live servers (or 90 s pass), updating the strip and its alerts on every read.
    // live_servers comes from the last startup block of the log, so it can be the previous run's count: success
    // only while dnscrypt-proxy runs. The first read, right after the restart, decides nothing: the new process
    // may not have logged its startup line yet (old count) or written its pidfile (not running) at that moment.
    function waitForLiveServers($btn, until, first) {
        apiGet('service/status', function (st, status) {
            const read = status === 'success' && st;
            if (read) {
                lastStatus = st;
                renderStatus();
            }
            const done = !first && read;
            if (done && st.running === true && st.live_servers !== null && st.live_servers !== undefined) {
                busy($btn, false);
                showMessages('success', [T.appliedOk]);
                updateServiceControlUI('dnscryptroutes');
            } else if (done && st.running === false) {
                busy($btn, false);
                showMessages('warning', [T.notRunning]);
                updateServiceControlUI('dnscryptroutes');
            } else if (Date.now() >= until) {
                busy($btn, false);
                showMessages('warning', [T.noLiveServers]);
                updateServiceControlUI('dnscryptroutes');
            } else {
                setTimeout(function () { waitForLiveServers($btn, until, false); }, 3000);
            }
        });
    }

    $('#dr_save_apply').click(function () {
        const $btn = $(this);
        busy($btn, true);
        saveAll().done(function () {
            apply($btn);
        }).fail(function () {
            busy($btn, false);
        });
    });

    $('#dr_save_test').click(function () {
        const $btn = $(this);
        busy($btn, true);
        saveAll().done(function () {
            apiPost('service/testStart', {}, function (resp, status) {
                if (status === 'success' && resp && (resp.started || resp.reason === 'already-running')) {
                    if (resp.started) {
                        changedSinceTest = false;  // the new run renders the settings just saved
                        sessionRun = true;
                    } else {
                        sessionRun = false;  // a run started elsewhere: its settings are unknown here
                        showMessages('info', [T.testAlready]);
                    }
                    pollTest($btn);
                } else {
                    busy($btn, false);
                    showMessages('danger', [T.testNotStarted + ' ' + ((resp && resp.reason) || T.failedGeneric)]);
                }
            });
        }).fail(function () {
            busy($btn, false);
        });
    });

    $('#dr_test_apply').click(function () {
        apply($(this));
    });

    // poll service/testStatus every 3 s while the test runs; a newer chain (testGen) makes older callbacks no-ops
    function pollTest($btn) {
        const gen = ++testGen;
        clearTimeout(testTimer);
        apiGet('service/testStatus', function (resp, status) {
            if (gen !== testGen) {
                return;
            }
            const state = (status === 'success' && resp) ? resp.state : 'failed';
            renderTest(resp || {});
            if (state === 'running') {
                if ($btn) {
                    busy($btn, true);
                }
                testTimer = setTimeout(function () { pollTest($btn); }, 3000);
            } else if ($btn) {
                busy($btn, false);
                if (sessionRun && model.enabled !== '1' && !changedSinceTest) {
                    showMessages('warning', [T.testRoutingOff]);
                }
            }
        });
    }

    function protoLabel(proto) {
        const labels = {dnscrypt: 'DNSCrypt', doh: 'DoH', odoh: 'ODoH'};
        return labels[norm(proto)] || String(proto || '');
    }

    function renderTest(r) {
        lastTest = r;
        if (!r.state || r.state === 'idle') {
            $('#dr_testpanel').hide();
            return;
        }
        $('#dr_testpanel').show();
        // The test renders the saved settings. With the saved Enable off that is the stock output (or the
        // manual 90-eu override), not the matrix routes. Save & Test saves the checkbox first, so the saved
        // state is what the test used, unless a write on this page changed it since (then only "settings changed").
        // A result from before this page was loaded may have run with another Enable state: neutral labels then.
        const known = sessionRun && modelLoaded && !changedSinceTest;
        const routingOff = known && model.enabled !== '1';
        const offNote = routingOff ? alertBox('warning', '<i class="fa fa-exclamation-triangle"></i> ' + esc(T.testRoutingOff)) : '';
        if (r.state === 'running') {
            $('#dr_test_head').html('<i class="fa fa-spinner fa-pulse"></i> ' + esc(known && !routingOff ? T.testRunning : T.testRunningNeutral) + (r.started ? ' · ' + esc(fmtTime(r.started)) : ''));
            $('#dr_test_note').html(offNote);
            $('#dr_test_error').empty();
            $('#dr_test_table > tbody').empty();
            $('#dr_test_queries').empty();
            $('#dr_test_unknown').hide();
            $('#dr_test_relays').hide();
            $('#dr_test_apply').hide();
            return;
        }
        let head = '<b>' + esc(!known ? T.lastTestNeutral : (routingOff ? T.lastTestOff : T.lastTest)) + '</b> ' + esc(fmtTime(r.started));
        if (r.duration_s !== null && r.duration_s !== undefined) {
            head += ' · ' + esc(Math.round(r.duration_s)) + ' s';
        }
        head += ' · ' + esc(T.instanceStopped);
        $('#dr_test_head').html(head);
        let notes = offNote;
        if (changedSinceTest) {
            notes += alertBox('warning', '<i class="fa fa-exclamation-triangle"></i> ' + esc(T.testOutdated));
        }
        $('#dr_test_note').html(notes);

        let error = '';
        if (r.state === 'failed') {
            const labels = {timeout: T.errTimeout, 'check-failed': T.errCheck, crashed: T.errCrashed};
            error = '<b>' + esc(T.testFailed) + '</b> ' + esc(labels[r.error] || r.error || '');
            if (r.check && r.check.output) {
                error += '<pre style="margin-top: 5px; white-space: pre-wrap;">' + esc(r.check.output) + '</pre>';
            }
        }
        $('#dr_test_error').html(error ? alertBox('danger', error) : '');

        let rows = '';
        let unknown = false;
        let routed = false;
        (r.resolvers || []).forEach(function (res) {
            let route = '—';
            if (res.routes && res.routes.length) {
                routed = true;
                route = esc(T.via) + ' ' + esc(res.routes.join(', '));
            } else if (res.direct) {
                route = '<span class="text-danger">' + esc(T.directRoute) + '</span>';
            }
            let cert = esc(res.cert);
            if (res.cert === 'ok') {
                cert = 'OK (' + esc(protoLabel(res.proto)) + ')';
            } else if (res.cert === 'unknown') {
                unknown = true;
                cert = 'unknown *';
            }
            let result = '<span class="text-success"><i class="fa fa-check"></i> ' + esc(T.pass) + '</span>';
            if (!res.pass) {
                let why = T.failError;
                if (res.direct) {
                    why = T.failDirect;
                } else if (res.cert === 'ok' && norm(res.proto) !== 'dnscrypt') {
                    why = T.failProto;
                } else if (res.cert === 'timeout') {
                    why = T.failNoAnswer;
                } else if (res.cert === 'unknown') {
                    why = T.failUnused;
                } else if (res.cert === 'ok') {
                    why = T.failNoRoute;
                }
                result = '<span class="text-danger"><i class="fa fa-times"></i> ' + esc(why) + '</span>';
            }
            rows += '<tr><td>' + esc(res.name) + '</td><td>' + route + '</td><td>' + cert + '</td><td>' +
                (res.rtt_ms !== null && res.rtt_ms !== undefined ? esc(res.rtt_ms) + ' ms' : '—') + '</td><td>' + result + '</td></tr>';
        });
        $('#dr_test_table > tbody').html(rows);
        $('#dr_test_unknown').toggle(unknown);
        $('#dr_test_relays').toggle(routed);
        const queries = (r.queries || []).map(function (q) { return esc(q.name) + ' ' + esc(q.type) + ' ' + esc(q.rcode); });
        $('#dr_test_queries').html(queries.length ? esc(T.queriesVia) + ' ' + queries.join(' · ') : '');
        // no Apply from an outdated result, nor from a render that would stop DNS (fail-closed marker), nor after a
        // run with routing off (it would only restart the configuration already live)
        const failClosed = !!(r.check && r.check.output && String(r.check.output).indexOf('Apply would stop DNS (fail closed)') >= 0);
        $('#dr_test_apply').toggle(!changedSinceTest && !failClosed && !routingOff);
    }

    /* ------------------------------------------------------------ status strip and notices (C-02 + pending) */

    function loadStatus() {
        return apiGet('service/status', function (st, status) {
            if (status === 'success' && st) {
                lastStatus = st;
                renderStatus();
            }
        });
    }

    // core's service widget (updateServiceControlUI) has no after-action hook: follow its start/stop/restart
    // calls and re-read the strip, every 3 s while the service runs without live servers yet (bound 90 s)
    function followService(until) {
        apiGet('service/status', function (st, status) {
            if (status === 'success' && st) {
                lastStatus = st;
                renderStatus();
            }
            if (st && st.running && (st.live_servers === null || st.live_servers === undefined) && Date.now() < until) {
                setTimeout(function () { followService(until); }, 3000);
            }
        });
    }
    $(document).ajaxComplete(function (event, xhr, settings) {
        if (/^\/api\/dnscryptroutes\/service\/(start|stop|restart)$/.test(settings.url || '')) {
            followService(Date.now() + 90000);
        }
    });

    function renderStatus() {
        const st = lastStatus;
        if (!st) {
            return;
        }
        const policy = {
            'applied': ['text-success', T.applied],
            'not-applied': ['text-danger', T.notApplied],
            'invariant-violated': ['text-danger', T.refused],
            'disabled': ['text-muted', T.off],
            'base-disabled': ['text-muted', T.baseOff]
        }[st.override] || ['text-muted', st.override || '—'];
        // dnscrypt-proxy not running: the generated file and the old log lines say nothing about live DNS
        // (base-disabled keeps its own label: the stock service is switched off on purpose)
        const stopped = st.running === false && st.override !== 'base-disabled';
        $('#dr_policy').attr('class', stopped ? 'text-danger' : policy[0]).text(stopped ? T.stopped : policy[1]);
        const live = (st.running === false || st.live_servers === null || st.live_servers === undefined) ? '—' : st.live_servers;
        $('#dr_live').text(live + ' / ' + (st.total_servers || 0));
        $('#dr_applied').text(st.applied && st.applied.time ? fmtTime(st.applied.time) : T.never);
        if (isDirty()) {
            $('#dr_pending').attr('class', 'text-warning').text(T.unsaved);
        } else if (st.pending) {
            $('#dr_pending').attr('class', 'text-warning').text(T.savedNotApplied);
        } else {
            $('#dr_pending').attr('class', 'text-muted').text(T.none);
        }

        const routingOn = model.enabled === '1';
        const alerts = [];
        if (st.override === 'invariant-violated') {
            alerts.push(esc(T.invariant));
        }
        if (st.override === 'not-applied') {
            alerts.push(esc(T.notAppliedAlert));
        }
        // only while the plugin's routing is in effect; with routing off, stock dnscrypt-proxy is direct by design
        const routingInEffect = st.override !== 'disabled' && st.override !== 'base-disabled';
        if (routingInEffect && st.direct_servers && st.direct_servers.length) {
            alerts.push(esc(T.direct) + ' <b>' + esc(st.direct_servers.join(', ')) + '</b>');
        }
        if (routingOn && model.skip !== '1') {
            alerts.push(esc(T.skipOff));
        }
        $('#dr_alerts').html(alerts.map(function (a) {
            return alertBox('danger', '<i class="fa fa-exclamation-circle"></i> ' + a);
        }).join(''));

        const notices = [];
        // the applied state decides (generated file), not the saved Enable: until Apply the kit stays live
        if (st.manual_override_present && routingInEffect) {
            notices.push(esc(T.shadowed));
        }
        if (st.manual_template_without_mapping) {
            notices.push(esc(T.leftover));
        }
        // the stock lists matter only while routing is applied or saved to be applied (then they are overridden)
        if (stockListsInUse && (routingOn || routingInEffect)) {
            notices.push(esc(T.stockLists));
        }
        $('#dr_notices').html(notices.map(function (n) {
            return alertBox('info', '<i class="fa fa-info-circle"></i> ' + n);
        }).join(''));
    }

    /* ------------------------------------------------------------ relay grid and dialogs */

    $('#grid-relays').UIBootgrid({
        search: API + 'settings/searchRelay',
        get: API + 'settings/getRelay/',
        set: API + 'settings/setRelay/',
        add: API + 'settings/addRelay/',
        del: API + 'settings/delRelay/',
        options: {
            selection: false,
            multiSelect: false,
            disableScroll: true,  // the grid is not the last element of the page: size it to its rows
            formatters: {
                relayname: function (column, row) {
                    const name = htmlDecode(row.name);
                    const loc = locationOf('relays', name);
                    return esc(name) + (loc ? ' <small class="text-muted">' + esc(loc) + '</small>' : '');
                }
            }
        },
        // own handlers: the C-03 write responses always carry "validations", and refusals must be shown
        commands: {
            add: {method: function () { openDialog('relay', null); }},
            edit: {method: function () { openDialog('relay', String($(this).data('row-id'))); }},
            delete: {method: function () { deleteItem('relay', String($(this).data('row-id'))); }},
            copy: {classname: undefined}
        }
    });

    function dialogOf(kind) {
        return kind === 'relay' ? 'dialogRelay' : 'dialogResolver';
    }
    function endpointOf(kind) {
        return kind === 'relay' ? 'Relay' : 'Resolver';
    }

    function dialogAlert(dlg, messages) {
        const $body = $('#' + dlg + ' .modal-body');
        $body.find('.dr-dialog-alert').remove();
        if (messages.length) {
            $body.prepend('<div class="alert alert-danger dr-dialog-alert">' + msgList(messages) + '</div>');
        }
    }

    // searchable catalog picker (catalog/get): name, country, description; fills name and operator
    function fillPicker(kind) {
        const $select = byId('catalog_' + kind);
        const list = kind === 'relay' ? catalog.relays : catalog.resolvers;
        $select.empty();
        if (!catalog.available) {
            $select.append($('<option/>').val('').text(T.noCatalog));
        } else {
            $select.append($('<option/>').val('').text('—'));
            (list || []).forEach(function (entry) {
                const usable = kind === 'relay' || entry.proto === 'dnscrypt';
                const parts = [];
                if (entry.location) {
                    parts.push(String(entry.location).toUpperCase());
                }
                if (kind === 'resolver') {
                    parts.push(usable ? protoLabel(entry.proto) : protoLabel(entry.proto) + ', ' + T.notDnscrypt);
                }
                if (entry.description) {
                    const text = String(entry.description).replace(/\s+/g, ' ');
                    parts.push(text.length > 90 ? text.substring(0, 87) + '…' : text);
                }
                $select.append($('<option/>').val(entry.name).text(entry.name)
                    .attr('data-subtext', parts.join(' · '))
                    .attr('data-tokens', entry.name + ' ' + (entry.description || ''))
                    .attr('title', entry.name)
                    .prop('disabled', !usable));
            });
        }
        $select.val('');
        $select.selectpicker('refresh');
    }

    $('#catalog_relay, #catalog_resolver').change(function () {
        const kind = this.id === 'catalog_relay' ? 'relay' : 'resolver';
        const entry = catalogEntry(kind === 'relay' ? 'relays' : 'resolvers', $(this).val());
        if (entry) {
            byId(kind + '.name').val(entry.name);
            byId(kind + '.operator').val(entry.operator_guess || '');
        }
    });

    function openDialog(kind, uuid) {
        const dlg = dialogOf(kind);
        const map = {};
        map['frm_' + dlg] = API + 'settings/get' + endpointOf(kind) + '/' + (uuid || '');
        mapDataToFormUI(map).done(function () {
            fillPicker(kind);
            if (kind === 'resolver' && uuid && edits[uuid]) {
                // show the unsaved ticks of this row; saving the dialog saves them
                byId('resolver.relays').val(edits[uuid].relays);
                byId('resolver.enabled').prop('checked', edits[uuid].enabled === '1');
            }
            $('#' + dlg + ' select.selectpicker').selectpicker('refresh');
            clearFormValidation('frm_' + dlg);
            dialogAlert(dlg, []);
            $('#' + dlg).modal({backdrop: 'static', keyboard: false});
            $('#btn_' + dlg + '_save').unbind('click').click(function () {
                saveDialog(kind, uuid);
            });
        });
    }

    // split C-03 messages: fields of the edited (or new) row go to the dialog fields, all others are listed above them
    function splitDialogErrors(kind, uuid, validations) {
        const collection = kind === 'relay' ? 'relays\\.relay' : 'resolvers\\.resolver';
        const re = new RegExp('^dnscryptroutes\\.' + collection + '\\.([^.]+)\\.([A-Za-z]+)$');
        const known = (kind === 'relay' ? model.relays : model.resolvers).map(function (r) { return r.uuid; });
        const fields = {};
        const other = [];
        $.each(validations || {}, function (path, message) {
            const m = re.exec(path);
            const ownRow = m && (uuid ? m[1] === uuid : known.indexOf(m[1]) < 0);
            if (ownRow && byId(kind + '.' + m[2]).length) {
                fields[kind + '.' + m[2]] = message;
            } else {
                other.push(message);
            }
        });
        return {fields: fields, other: other};
    }

    function saveDialog(kind, uuid) {
        const dlg = dialogOf(kind);
        const $btn = $('#btn_' + dlg + '_save');
        if ($btn.find('i').hasClass('fa-spinner')) {
            return;
        }
        $btn.find('i').addClass('fa fa-spinner fa-pulse');
        const url = 'settings/' + (uuid ? 'set' + endpointOf(kind) + '/' + uuid : 'add' + endpointOf(kind));
        apiPost(url, getFormData('frm_' + dlg), function (resp, status) {
            $btn.find('i').removeClass('fa fa-spinner fa-pulse');
            if (status === 'success' && resp && resp.result === 'saved') {
                $('#' + dlg).modal('hide');
                if (kind === 'resolver' && uuid) {
                    delete edits[uuid];
                }
                afterWrite(resp);
            } else {
                const split = splitDialogErrors(kind, uuid, resp && resp.validations);
                handleFormValidation('frm_' + dlg, split.fields);
                let other = split.other;
                if (!other.length && !Object.keys(split.fields).length) {
                    other = [T.failedGeneric];
                }
                dialogAlert(dlg, other);
            }
        });
    }

    // grid delete: no confirmation; a refusal (C-03 failure format) is shown and nothing changes
    function deleteItem(kind, uuid) {
        const item = kind === 'relay' ? findRelay(uuid) : findResolver(uuid);
        apiPost('settings/del' + endpointOf(kind) + '/' + uuid, {}, function (resp, status) {
            if (status === 'success' && resp && resp.result === 'saved') {
                delete edits[uuid];
                afterWrite(resp);
            } else {
                const messages = [];
                $.each((resp && resp.validations) || {}, function (path, message) { messages.push(message); });
                stdDialogInform(T.notDeleted + (item ? ': ' + esc(item.name) : ''), msgList(messages.length ? messages : [T.failedGeneric]), T.close, undefined, 'warning');
            }
        });
    }

    // after a successful dialog save or delete: the saved settings changed and earlier set errors are stale
    function afterWrite(resp) {
        changedSinceTest = true;
        clearSetErrors();
        showWarnings(resp.warnings);
        $('#grid-relays').bootgrid('reload');
        reloadModel().always(loadStatus);
    }

    /* ------------------------------------------------------------ General form */

    function ecsUi() {
        const on = byId('dnscryptroutes.general.ecsEnabled').is(':checked');
        byId('dnscryptroutes.general.ecsSubnet').prop('disabled', !on);
        $('#dr_ecs_warning').toggle(on);
    }

    byId('dnscryptroutes.general.ecsSubnet').after(
        '<div id="dr_ecs_warning" class="text-warning small" style="display: none; margin-top: 4px;">' +
        '<i class="fa fa-exclamation-triangle"></i> ' +
        esc(T.ecsWarning) +
        '</div>'
    );

    /* ------------------------------------------------------------ page load */

    window.addEventListener('beforeunload', function (e) {
        if (isDirty()) {
            e.preventDefault();
            e.returnValue = '';
        }
    });

    apiGet('catalog/get', function (data, status) {
        if (status === 'success' && data) {
            catalog = data;
            renderMatrix();
            $('#grid-relays').bootgrid('reload');
        }
    });

    mapDataToFormUI({'frm_general': API + 'settings/get'}).done(function (data) {
        $('.selectpicker').selectpicker('refresh');
        ecsUi();
        setModel(readModel(decodeAll(data['frm_general'] || {})));
        $('#frm_general').on('change', 'input, select', function () {
            formDirty = true;
            renderStatus();
        });
        byId('dnscryptroutes.general.ecsEnabled').change(ecsUi);
    });

    // stock lists at page load, read from the stock settings; silently skipped without access to that page (ACL)
    $.ajax({url: '/api/dnscryptproxy/general/get', dataType: 'json', global: false}).done(function (data) {
        const general = (data && data.general) || {};
        const used = function (list) {
            return Object.keys(list || {}).some(function (key) { return key !== '' && String(list[key].selected) !== '0'; });
        };
        stockListsInUse = used(general.serverlist) || used(general.relaylist);
        renderStatus();
    });

    loadStatus();
    pollTest(null);
    updateServiceControlUI('dnscryptroutes');
});
</script>
