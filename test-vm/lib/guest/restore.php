<?php
// Runs in the guest (vm restore, via `php -- <file>` on stdin). Imports a whole config.xml the way
// System > Configuration > Backups does for a full restore (diag_backup.php: Config::restoreBackup),
// without areas, decryption or RRD data. Prints the SHA-256 of the resulting /conf/config.xml.
// Installs no packages and restores no files; the caller reboots.
require_once('script/load_phalcon.php');

use OPNsense\Core\Config;

$file = $argv[1] ?? '';
if ($file === '' || !is_file($file)) {
    fwrite(STDERR, "restore: no such file '$file'\n");
    exit(1);
}
$xml = @simplexml_load_file($file);
if ($xml === false || $xml->getName() !== 'opnsense') {
    fwrite(STDERR, "restore: '$file' is not an OPNsense config.xml\n");
    exit(1);
}
if (!Config::getInstance()->restoreBackup($file)) {
    fwrite(STDERR, "restore: the configuration could not be loaded; the previous one was kept\n");
    exit(1);
}
echo hash_file('sha256', '/conf/config.xml') . "\n";
