<?php

namespace OPNsense\DnscryptRoutes\Api;

use OPNsense\Base\ApiMutableServiceControllerBase;
use OPNsense\Core\Backend;
use OPNsense\DnscryptRoutes\DnscryptRoutes;

/**
 * service/* (C-03). Apply uses the stock os-dnscrypt-proxy service and template, exactly like the
 * stock plugin; this controller adds the rule check before it and the applied record after it.
 */
class ServiceController extends ApiMutableServiceControllerBase
{
    use RuleCheckTrait;

    protected static $internalServiceClass = '\OPNsense\Dnscryptproxy\General';
    protected static $internalServiceEnabled = 'enabled';
    protected static $internalServiceTemplate = 'OPNsense/Dnscryptproxy';
    protected static $internalServiceName = 'dnscryptproxy';

    /**
     * Save & Apply, second half: re-check the saved model (R-06, R-21), then template reload and
     * restart through the parent, then record the applied hash and time.
     */
    public function reconfigureAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed'];
        }
        // not $this->getModel(): in this controller that is the stock service model
        $mdl = new DnscryptRoutes();
        $errors = $this->ruleErrors($mdl, $this->loadCatalog());
        if (count($errors) > 0) {
            return ['status' => 'failed', 'result' => 'failed', 'validations' => $errors];
        }
        $hash = $this->modelHash();
        $result = parent::reconfigureAction();
        if (($result['status'] ?? 'failed') !== 'failed') {
            $recorded = json_decode(trim((new Backend())->configdRun('dnscryptroutes mark-applied ' . $hash) ?? ''), true);
            if (!is_array($recorded) || empty($recorded['ok'])) {
                $result['status'] = 'failed';
                $result['status_msg'] = gettext('Applied, but the applied state could not be recorded.');
            }
        }
        return $result;
    }

    /**
     * Stock service status merged with the C-02 status action, plus pending changes.
     */
    public function statusAction()
    {
        $stock = parent::statusAction();
        $extra = json_decode(trim((new Backend())->configdRun('dnscryptroutes status') ?? ''), true);
        if (!is_array($extra)) {
            $extra = [
                'running' => false,
                'live_servers' => null,
                'total_servers' => 0,
                'override' => 'disabled',
                'direct_servers' => [],
                'manual_override_present' => false,
                'manual_template_without_mapping' => false,
                'applied' => null,
            ];
        }
        $applied = $extra['applied'] ?? null;
        $extra['pending'] = !is_array($applied) || ($applied['hash'] ?? '') !== $this->modelHash();
        return array_merge($stock, $extra);
    }

    public function testStartAction()
    {
        if (!$this->request->isPost()) {
            return ['started' => false, 'reason' => 'not-post'];
        }
        $result = json_decode(trim((new Backend())->configdRun('dnscryptroutes test-start') ?? ''), true);
        return is_array($result) ? $result : ['started' => false, 'reason' => 'backend-error'];
    }

    public function testStatusAction()
    {
        $result = json_decode(trim((new Backend())->configdRun('dnscryptroutes test-status') ?? ''), true);
        if (is_array($result)) {
            return $result;
        }
        // backend failed: still a complete C-04 object
        return [
            'state' => 'failed', 'started' => null, 'finished' => null, 'duration_s' => null,
            'error' => 'crashed', 'check' => ['ok' => false, 'output' => ''], 'live_servers' => null,
            'resolvers' => [], 'queries' => [],
        ];
    }
}
