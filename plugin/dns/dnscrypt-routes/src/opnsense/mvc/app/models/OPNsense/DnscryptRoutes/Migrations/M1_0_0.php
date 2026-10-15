<?php

namespace OPNsense\DnscryptRoutes\Migrations;

use OPNsense\Base\BaseModelMigration;

/**
 * Seeds a fresh install with the vetted preset (C-01), routing disabled.
 * An existing configuration is never touched.
 */
class M1_0_0 extends BaseModelMigration
{
    public function run($model)
    {
        if (count(iterator_to_array($model->resolvers->resolver->iterateItems())) > 0) {
            return;
        }
        if (count(iterator_to_array($model->relays->relay->iterateItems())) > 0) {
            return;
        }
        $preset = json_decode(file_get_contents(dirname(__DIR__) . '/preset.json'), true);
        if (!is_array($preset)) {
            return;
        }

        $model->general->enabled = '0';
        $model->general->ecsEnabled = '0';
        $model->general->ecsSubnet = '146.70.82.0/24';

        $uuids = [];
        foreach ($preset['relays'] as $relay) {
            $node = $model->relays->relay->Add();
            $node->name = $relay['name'];
            $node->operator = $relay['operator'];
            $uuids[$relay['name']] = $node->getAttributes()['uuid'];
        }
        foreach ($preset['resolvers'] as $resolver) {
            $node = $model->resolvers->resolver->Add();
            $node->enabled = (string)$resolver['enabled'];
            $node->name = $resolver['name'];
            $node->operator = $resolver['operator'];
            $refs = [];
            foreach ($resolver['relays'] as $relayName) {
                $refs[] = $uuids[$relayName];
            }
            $node->relays = implode(',', $refs);
        }
    }
}
