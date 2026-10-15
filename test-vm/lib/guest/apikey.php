<?php
// Runs in the guest (vm provision, via `php --` on stdin). Creates an API key for root with the same
// calls as the core endpoint api/auth/user/addApiKey (Auth/Api/UserController::addApiKeyAction:
// User::getUserByName, ApiKeyField::add, serializeToConfig, Config::save) and prints it as api.env lines.
require_once('script/load_phalcon.php');

use OPNsense\Core\Config;
use OPNsense\Auth\User;

Config::getInstance()->lock();
$mdl = new User();
$user = $mdl->getUserByName('root');
if ($user === null) {
    Config::getInstance()->unlock();
    fwrite(STDERR, "apikey: user root not found\n");
    exit(1);
}
$tmp = $user->apikeys->add();
if (empty($tmp['key']) || empty($tmp['secret'])) {
    Config::getInstance()->unlock();
    fwrite(STDERR, "apikey: could not create a key\n");
    exit(1);
}
$mdl->serializeToConfig(false, true);
Config::getInstance()->save();
echo "API_KEY=" . $tmp['key'] . "\n";
echo "API_SECRET=" . $tmp['secret'] . "\n";
