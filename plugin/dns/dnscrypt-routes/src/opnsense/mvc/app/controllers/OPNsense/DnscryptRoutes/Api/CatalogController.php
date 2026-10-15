<?php

namespace OPNsense\DnscryptRoutes\Api;

use OPNsense\Base\ApiControllerBase;

/**
 * catalog/get: the C-05 catalog from the `catalog` configd action.
 */
class CatalogController extends ApiControllerBase
{
    use RuleCheckTrait;

    public function getAction()
    {
        return $this->loadCatalog();
    }
}
