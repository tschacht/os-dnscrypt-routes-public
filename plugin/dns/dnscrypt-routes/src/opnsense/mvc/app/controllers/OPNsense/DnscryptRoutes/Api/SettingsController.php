<?php

namespace OPNsense\DnscryptRoutes\Api;

use OPNsense\Base\ApiMutableModelControllerBase;
use OPNsense\Core\Config;

/**
 * settings/* (C-03). Every write endpoint changes the model in memory, runs the full rule check
 * (performValidation + validateRouting with the catalog, R-06/R-21) on the resulting model and only
 * then saves through core save(). A refused call leaves config.xml untouched.
 */
class SettingsController extends ApiMutableModelControllerBase
{
    use RuleCheckTrait;

    protected static $internalModelName = 'dnscryptroutes';
    protected static $internalModelClass = 'OPNsense\DnscryptRoutes\DnscryptRoutes';

    /**
     * Check the (already modified) model; save it when it passes.
     * @param \OPNsense\DnscryptRoutes\DnscryptRoutes $mdl
     * @return array C-03 response
     */
    private function checkAndSave($mdl)
    {
        $catalog = $this->loadCatalog();
        $errors = $this->ruleErrors($mdl, $catalog);
        if (count($errors) > 0) {
            return $this->failure($errors);
        }
        // core save(): read-only user check, admin check, audit message; rules already ran on the full model
        $this->save(false, true);
        return [
            'result' => 'saved',
            'validations' => new \stdClass(),
            'warnings' => $mdl->getWarnings($this->catalogRelayNames($catalog)),
        ];
    }

    public function setAction()
    {
        if (!$this->request->isPost() || !$this->request->hasPost(static::$internalModelName)) {
            return ['result' => 'failed'];
        }
        Config::getInstance()->lock();
        $mdl = $this->getModel();
        $mdl->setNodes($this->request->getPost(static::$internalModelName));
        return $this->checkAndSave($mdl);
    }

    /**
     * Add (uuid null) or change one item of an ArrayField from the posted form.
     * @param string $key post key and item name ("relay" or "resolver")
     * @param string $path model path of the array ("relays.relay")
     * @param string|null $uuid
     * @return array
     */
    private function writeItem($key, $path, $uuid)
    {
        if (!$this->request->isPost() || !$this->request->hasPost($key)) {
            return ['result' => 'failed'];
        }
        Config::getInstance()->lock();
        $mdl = $this->getModel();
        if ($uuid === null) {
            $node = $mdl->getNodeByReference($path)->add();
        } else {
            $node = $mdl->getNodeByReference($path . '.' . $uuid);
            if ($node === null) {
                return ['result' => 'failed'];
            }
        }
        $node->setNodes($this->request->getPost($key));
        return $this->checkAndSave($mdl);
    }

    /**
     * Delete one item, then run the full rule check on the result.
     * @param string $path model path of the array
     * @param string|null $uuid
     * @param bool $refuseIfReferenced refuse while a resolver references the item (relays)
     * @return array
     */
    private function deleteItem($path, $uuid, $refuseIfReferenced)
    {
        if (!$this->request->isPost() || $uuid === null) {
            return ['result' => 'failed'];
        }
        Config::getInstance()->lock();
        $mdl = $this->getModel();
        if ($refuseIfReferenced && $mdl->isRelayReferenced($uuid)) {
            return $this->failure([
                'dnscryptroutes.' . $path . '.' . $uuid . '.name' => gettext('The relay is still used by a resolver.'),
            ]);
        }
        if (!$mdl->getNodeByReference($path)->del($uuid)) {
            return ['result' => 'failed'];
        }
        return $this->checkAndSave($mdl);
    }

    public function searchRelayAction()
    {
        return $this->searchBase('relays.relay', ['name', 'operator'], 'name');
    }

    public function getRelayAction($uuid = null)
    {
        return $this->getBase('relay', 'relays.relay', $uuid);
    }

    public function addRelayAction()
    {
        return $this->writeItem('relay', 'relays.relay', null);
    }

    public function setRelayAction($uuid = null)
    {
        return $this->writeItem('relay', 'relays.relay', $uuid);
    }

    public function delRelayAction($uuid = null)
    {
        return $this->deleteItem('relays.relay', $uuid, true);
    }

    public function searchResolverAction()
    {
        return $this->searchBase('resolvers.resolver', ['enabled', 'name', 'operator', 'relays'], 'name');
    }

    public function getResolverAction($uuid = null)
    {
        return $this->getBase('resolver', 'resolvers.resolver', $uuid);
    }

    public function addResolverAction()
    {
        return $this->writeItem('resolver', 'resolvers.resolver', null);
    }

    public function setResolverAction($uuid = null)
    {
        return $this->writeItem('resolver', 'resolvers.resolver', $uuid);
    }

    public function delResolverAction($uuid = null)
    {
        return $this->deleteItem('resolvers.resolver', $uuid, false);
    }
}
