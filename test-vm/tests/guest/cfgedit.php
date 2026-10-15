<?php
// Runs in the guest (vm test, via `php -- <op> ...` on stdin). A hand edit of the saved plugin settings that
// bypasses the API rule check (BaseModel::serializeToConfig with validation disabled), for the checks that
// need a config the API refuses (fail closed, V17).
//   relays <resolver name> <relay names, comma separated, or "-" for none>
//   operator <resolver name> <operator>
//   general <field> <value>
require_once('script/load_phalcon.php');

use OPNsense\Core\Config;
use OPNsense\DnscryptRoutes\DnscryptRoutes;

$op = $argv[1] ?? '';
Config::getInstance()->lock();
$mdl = new DnscryptRoutes();
$find = function ($items, $name) {
    foreach ($items->iterateItems() as $uuid => $node) {
        if ((string)$node->name === $name) {
            return [$uuid, $node];
        }
    }
    fwrite(STDERR, "cfgedit: no row named $name\n");
    exit(1);
};
if ($op === 'relays' && count($argv) === 4) {
    [, $resolver] = $find($mdl->resolvers->resolver, $argv[2]);
    $uuids = [];
    foreach ($argv[3] === '-' ? [] : explode(',', $argv[3]) as $name) {
        [$uuid] = $find($mdl->relays->relay, $name);
        $uuids[] = $uuid;
    }
    $resolver->relays = implode(',', $uuids);
} elseif ($op === 'operator' && count($argv) === 4) {
    [, $resolver] = $find($mdl->resolvers->resolver, $argv[2]);
    $resolver->operator = $argv[3];
} elseif ($op === 'general' && count($argv) === 4) {
    $mdl->general->{$argv[2]} = $argv[3];
} else {
    fwrite(STDERR, "usage: cfgedit.php relays <resolver> <relay,...|-> | operator <resolver> <op> | general <field> <value>\n");
    exit(2);
}
$mdl->serializeToConfig(false, true);
Config::getInstance()->save();
echo "edited\n";
