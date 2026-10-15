<?php

namespace OPNsense\DnscryptRoutes;

use OPNsense\Base\BaseModel;
use OPNsense\Base\Messages\Message;

/**
 * Model for per-resolver anonymized DNSCrypt routes (C-01).
 *
 * performValidation()  catalog-independent blocking rules (R-06)
 * validateRouting()    catalog-dependent blocking rules (R-06), C-05 catalog in
 * getWarnings()        non-blocking warnings (R-07)
 *
 * Path forms: performValidation() messages use model-relative paths
 * (resolvers.resolver.<uuid>.relays, general.enabled) because the API base
 * controller adds the model prefix itself. validateRouting() and getWarnings()
 * return the full C-03 form with the "dnscryptroutes." prefix on every path.
 * isRelayReferenced()  helper for refusing to delete a used relay
 */
class DnscryptRoutes extends BaseModel
{
    public const PRESET_ECS_SUBNET = '146.70.82.0/24';
    public const CATALOG_UNAVAILABLE = 'Start DNSCrypt-Proxy once so it downloads the signed resolver list.';

    private const PREFIX = 'dnscryptroutes';

    /** @return bool whether routing is enabled in the resulting model */
    private function routingEnabled()
    {
        return (string)$this->general->enabled === '1';
    }

    private static function full($path)
    {
        return self::PREFIX . '.' . $path;
    }

    private static function norm($value)
    {
        return strtolower(trim((string)$value));
    }

    private function resolverPath($uuid, $field)
    {
        return 'resolvers.resolver.' . $uuid . '.' . $field;
    }

    private function relayPath($uuid, $field)
    {
        return 'relays.relay.' . $uuid . '.' . $field;
    }

    /** @return array uuid => [name, operator] */
    private function relayIndex()
    {
        $index = [];
        foreach ($this->relays->relay->iterateItems() as $uuid => $relay) {
            $index[$uuid] = ['name' => (string)$relay->name, 'operator' => (string)$relay->operator];
        }
        return $index;
    }

    /** @return array of resolver rows: uuid, enabled, name, operator, relays (list of uuids) */
    private function resolverRows()
    {
        $rows = [];
        foreach ($this->resolvers->resolver->iterateItems() as $uuid => $resolver) {
            $refs = (string)$resolver->relays;
            $rows[] = [
                'uuid' => $uuid,
                'enabled' => (string)$resolver->enabled === '1',
                'name' => (string)$resolver->name,
                'operator' => (string)$resolver->operator,
                'relays' => $refs === '' ? [] : explode(',', $refs),
            ];
        }
        return $rows;
    }

    /**
     * Names of enabled stock static servers (os-dnscrypt-proxy). Overridable for tests.
     * @return array
     */
    protected function stockStaticServerNames()
    {
        $names = [];
        // Stock model os-dnscrypt-proxy: Server (mount //OPNsense/dnscryptproxy/server, servers.server[])
        if (!class_exists('\\OPNsense\\Dnscryptproxy\\Server')) {
            return $names;
        }
        $stock = new \OPNsense\Dnscryptproxy\Server();
        foreach ($stock->servers->server->iterateItems() as $server) {
            if ((string)$server->enabled === '1') {
                $names[] = (string)$server->name;
            }
        }
        return $names;
    }

    /**
     * Whether the stock "Server list" or "Relay list" is non-empty. Overridable for tests.
     * @return bool
     */
    protected function stockListsInUse()
    {
        // Stock model os-dnscrypt-proxy: General (mount //OPNsense/dnscryptproxy/general, serverlist/relaylist at its root)
        if (!class_exists('\\OPNsense\\Dnscryptproxy\\General')) {
            return false;
        }
        $stock = new \OPNsense\Dnscryptproxy\General();
        return trim((string)$stock->serverlist) !== '' || trim((string)$stock->relaylist) !== '';
    }

    /**
     * R-06 catalog-independent rules, all skipped entirely when routing is being turned off.
     * {@inheritdoc}
     */
    public function performValidation($validateFullModel = false)
    {
        $messages = parent::performValidation($validateFullModel);

        // $text is already translated and filled in (sprintf(gettext(...), names))
        $add = function ($path, $text) use ($messages) {
            $messages->appendMessage(new Message($text, $path));
        };

        if (!$this->routingEnabled()) {
            return $messages;
        }

        $relays = $this->relayIndex();

        // dnscrypt-proxy route() reads a via entry "*" as any relay and "sdns:..." as a relay stamp,
        // which would bypass the operator rule below (M4-A-F1). No real relay name has either form.
        // Checked only while routing is on (R-06: turning routing off is always allowed, M4-A-F3); the
        // disabled template never reads relays, and the enabled template fails closed on such a name.
        foreach ($relays as $uuid => $relay) {
            $name = self::norm($relay['name']);
            if (strpos($name, '*') !== false || strpos($name, 'sdns:') === 0) {
                $add($this->relayPath($uuid, 'name'), sprintf(
                    gettext('Relay name %s is not a relay name: dnscrypt-proxy reads * as any relay and sdns: as a server stamp. Enter the name from the signed relay list (relays.md), for example anon-cs-fr.'),
                    $relay['name']
                ));
            }
        }

        $rows = $this->resolverRows();
        $stockNames = $this->stockStaticServerNames();
        $enabledCount = 0;
        $enabledNames = [];

        foreach ($rows as $row) {
            $relayPath = $this->resolverPath($row['uuid'], 'relays');
            if (self::norm($row['operator']) === '') {
                $add($this->resolverPath($row['uuid'], 'operator'), sprintf(
                    gettext('Resolver %s has no operator. Enter the operator that runs it (for example cryptostorm).'),
                    $row['name']
                ));
            }
            if ($row['enabled']) {
                $enabledCount++;
                $enabledNames[self::norm($row['name'])] = $row['uuid'];
                if (count($row['relays']) === 0) {
                    $add($relayPath, sprintf(
                        gettext('Resolver %s is enabled but has no relay. Choose at least one relay, or disable the resolver.'),
                        $row['name']
                    ));
                }
            }
            foreach ($row['relays'] as $relayUuid) {
                if (!isset($relays[$relayUuid])) {
                    $add($relayPath, sprintf(
                        gettext('Resolver %s refers to a relay that no longer exists. Choose its relays again.'),
                        $row['name']
                    ));
                    continue;
                }
                $relay = $relays[$relayUuid];
                if (self::norm($relay['operator']) === '') {
                    $add($this->relayPath($relayUuid, 'operator'), sprintf(
                        gettext('Relay %s has no operator. Enter the operator that runs it.'),
                        $relay['name']
                    ));
                } elseif (self::norm($relay['operator']) === self::norm($row['operator'])) {
                    $add($relayPath, sprintf(
                        gettext('Relay %s has the same operator as resolver %s. Choose a relay run by a different operator.'),
                        $relay['name'],
                        $row['name']
                    ));
                }
                if (self::norm($relay['name']) === 'anon-' . self::norm($row['name'])) {
                    $add($relayPath, sprintf(
                        gettext('Relay %s is the same server as resolver %s. Choose a different relay.'),
                        $relay['name'],
                        $row['name']
                    ));
                }
            }
        }

        if ($enabledCount === 0) {
            $add(
                $this->general->enabled->__reference,
                gettext('Routing needs at least one enabled resolver. Enable a resolver, or untick Enable anonymized routing.')
            );
        }

        foreach ($stockNames as $stockName) {
            $key = self::norm($stockName);
            if (isset($enabledNames[$key])) {
                $add($this->resolverPath($enabledNames[$key], 'name'), sprintf(
                    gettext('The enabled stock static server %s has the same name as this resolver and would replace its catalog entry. Rename or disable the stock static server.'),
                    $stockName
                ));
            }
        }

        return $messages;
    }

    /**
     * R-06 catalog-dependent rules.
     * @param array $catalog C-05 catalog
     * @return array {path: message}
     */
    public function validateRouting(array $catalog)
    {
        $errors = [];
        if (!$this->routingEnabled()) {
            return $errors;
        }
        if (empty($catalog['available'])) {
            $errors[self::full($this->general->enabled->__reference)] = gettext(self::CATALOG_UNAVAILABLE);
            return $errors;
        }
        $proto = [];
        foreach (($catalog['resolvers'] ?? []) as $entry) {
            $proto[$entry['name']] = $entry['proto'] ?? 'other';
        }
        foreach ($this->resolverRows() as $row) {
            if (!$row['enabled']) {
                continue;
            }
            $path = self::full($this->resolverPath($row['uuid'], 'name'));
            if (!isset($proto[$row['name']])) {
                $errors[$path] = sprintf(
                    gettext('Resolver %s is not in the signed resolver list (public-resolvers.md); it may be retired or mistyped. Check the name, or disable the resolver.'),
                    $row['name']
                );
            } elseif ($proto[$row['name']] !== 'dnscrypt') {
                $errors[$path] = sprintf(
                    gettext('Resolver %s is not a DNSCrypt server; only DNSCrypt resolvers can be anonymized. Disable it or choose another.'),
                    $row['name']
                );
            }
        }
        return $errors;
    }

    /**
     * R-07 warnings (non-blocking).
     * @param array $catalogNames relay names in the catalog (empty when no catalog is cached)
     * @return array list of {path, message}
     */
    public function getWarnings(array $catalogNames)
    {
        $warnings = [];
        // $text is already translated (gettext(...), with sprintf for names)
        $add = function ($path, $text) use (&$warnings) {
            $warnings[] = ['path' => self::full($path), 'message' => $text];
        };

        foreach ($this->resolverRows() as $row) {
            if ($row['enabled'] && count($row['relays']) === 1) {
                $add($this->resolverPath($row['uuid'], 'relays'), sprintf(
                    gettext('⚠ %s has a single relay. It is allowed but has no failover.'),
                    $row['name']
                ));
            }
        }
        if (count($catalogNames) > 0) {
            $known = array_flip($catalogNames);
            foreach ($this->relayIndex() as $uuid => $relay) {
                if (!isset($known[$relay['name']])) {
                    $add($this->relayPath($uuid, 'name'), sprintf(
                        gettext('Relay %s is not in the signed relay list (relays.md); it may be retired or mistyped. dnscrypt-proxy skips routes through an unknown relay.'),
                        $relay['name']
                    ));
                }
            }
        }
        if (
            (string)$this->general->ecsEnabled === '1'
            && trim((string)$this->general->ecsSubnet) !== self::PRESET_ECS_SUBNET
        ) {
            $add($this->general->ecsSubnet->__reference, gettext('This subnet may reveal your real network.'));
        }
        if ($this->stockListsInUse()) {
            $add(
                $this->general->enabled->__reference,
                gettext('The stock Server list / Relay list is not empty; it is overridden while anonymized routing is enabled, as are the stock DNSCrypt/DoH/ODoH protocol settings.')
            );
        }
        if ((string)$this->general->skipIncompatible !== '1') {
            $add(
                $this->general->skipIncompatible->__reference,
                gettext('Skip incompatible is off: a resolver that cannot be reached through its relays is queried directly.')
            );
        }
        return $warnings;
    }

    /**
     * Whether any resolver references the relay (for refusing delRelay).
     * @param string $relayUuid
     * @return bool
     */
    public function isRelayReferenced($relayUuid)
    {
        foreach ($this->resolverRows() as $row) {
            if (in_array($relayUuid, $row['relays'], true)) {
                return true;
            }
        }
        return false;
    }
}
