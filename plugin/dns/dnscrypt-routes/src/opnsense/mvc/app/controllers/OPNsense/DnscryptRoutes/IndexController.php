<?php

namespace OPNsense\DnscryptRoutes;

/**
 * The one page: Services > DNSCrypt-Proxy > Anonymized Routing (/ui/dnscryptroutes).
 */
class IndexController extends \OPNsense\Base\IndexController
{
    public function indexAction()
    {
        $this->view->generalForm = $this->getForm('general');
        $this->view->formDialogRelay = $this->getForm('dialogRelay');
        $this->view->formDialogResolver = $this->getForm('dialogResolver');
        $this->view->pick('OPNsense/DnscryptRoutes/index');
    }
}
