<?php

namespace OPNsense\DnscryptRoutes\Api;

use OPNsense\Core\Backend;
use OPNsense\Core\Config;
use OPNsense\DnscryptRoutes\DnscryptRoutes;

/**
 * Shared by SettingsController, ServiceController and CatalogController: catalog access, the full
 * rule check (R-06, R-21) and the model hash behind "pending changes" (C-03).
 */
trait RuleCheckTrait
{
    /**
     * C-05 catalog from the configd action; an unavailable catalog when the action fails.
     * @return array
     */
    protected function loadCatalog()
    {
        $raw = trim((new Backend())->configdRun('dnscryptroutes catalog') ?? '');
        $catalog = json_decode($raw, true);
        if (!is_array($catalog) || !array_key_exists('available', $catalog)) {
            return ['available' => false, 'source_dir' => '', 'resolvers' => [], 'relays' => []];
        }
        return $catalog;
    }

    /**
     * @param array $catalog C-05 catalog
     * @return array relay names in the catalog (empty when no catalog is cached)
     */
    protected function catalogRelayNames(array $catalog)
    {
        if (empty($catalog['available'])) {
            return [];
        }
        $names = [];
        foreach (($catalog['relays'] ?? []) as $relay) {
            $names[] = $relay['name'];
        }
        return $names;
    }

    /**
     * Full rule check on the model as it is now: performValidation(true) plus validateRouting(catalog).
     * performValidation() reports model-relative fields, so the "dnscryptroutes." prefix is added here;
     * validateRouting() already returns full paths.
     * @param DnscryptRoutes $mdl
     * @param array $catalog
     * @return array {path: message}, empty when the model may be saved or applied
     */
    protected function ruleErrors(DnscryptRoutes $mdl, array $catalog)
    {
        $errors = [];
        foreach ($mdl->performValidation(true) as $msg) {
            $path = 'dnscryptroutes.' . $msg->getField();
            $errors[$path] = isset($errors[$path]) ? $errors[$path] . ' ' . $msg->getMessage() : $msg->getMessage();
        }
        foreach ($mdl->validateRouting($catalog) as $path => $message) {
            $errors[$path] = isset($errors[$path]) ? $errors[$path] . ' ' . $message : $message;
        }
        return $errors;
    }

    /**
     * C-03 failure format.
     * @param array $errors {path: message}
     * @return array
     */
    protected function failure(array $errors)
    {
        return ['result' => 'failed', 'validations' => $errors];
    }

    /**
     * sha256 of the serialized model as stored in config.xml (the basis of "pending", C-03), without the
     * persisted_at attribute: core's BaseModel::toXML() stamps it with microtime(true) on every save, so a save
     * that changes nothing would otherwise count as a pending change. Apply and status both hash through here.
     * @return string
     */
    protected function modelHash()
    {
        $node = Config::getInstance()->object()->OPNsense->dnscryptroutes;
        if ($node->count() == 0) {
            return hash('sha256', '');
        }
        $copy = new \SimpleXMLElement((string)$node->asXML());
        unset($copy['persisted_at']);
        return hash('sha256', (string)$copy->asXML());
    }
}
