"""Check the architecture catalog offline without Django or production access."""
import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'catalog' / 'system.json'
STATUSES = {'documented', 'declared', 'inferred'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_sources(record):
    evidence = record.get('sources')
    require(isinstance(evidence, list) and evidence, f"{record['id']}: missing sources")
    for source in evidence:
        require(all(source.get(field) for field in ('label', 'type', 'url')),
                f"{record['id']}: incomplete source")
        address = urlsplit(source['url'])
        require(address.scheme == 'https' or source['url'].startswith('/wiki/'),
                f"{record['id']}: unsafe source scheme")
        require(not address.username and not address.password,
                f"{record['id']}: source URL contains user information")
        if source['type'] == 'wiki':
            page_id = str(UUID(source.get('page_id', '')))
            require(page_id in address.path.split('/'),
                    f"{record['id']}: source URL does not identify its page")


def check_catalog(catalog):
    require(catalog.get('schema_version') == 1, 'Unsupported schema version')
    require(catalog.get('id') == 'shizuha', 'Wrong catalog identity')
    datetime.fromisoformat(catalog['updated_at'].replace('Z', '+00:00'))
    require(catalog.get('coverage', {}).get('limitations'), 'Missing coverage limitations')
    node_records = catalog['nodes']
    nodes = {node['id']: node for node in node_records}
    require(len(nodes) == len(node_records), 'Duplicate node ID')
    require('shizuha' in nodes and nodes['shizuha']['parent_id'] is None, 'Missing root')
    for node in node_records:
        require(node.get('label') and node.get('kind') and node.get('description'),
                f"{node['id']}: incomplete node")
        require(node.get('status') in STATUSES, f"{node['id']}: invalid evidence status")
        check_sources(node)
        current = node
        visited = set()
        while current['id'] != 'shizuha':
            require(current['id'] not in visited, f"{node['id']}: parent cycle")
            visited.add(current['id'])
            parent = current.get('parent_id')
            require(parent in nodes, f"{node['id']}: missing parent")
            current = nodes[parent]
    edge_records = catalog['edges']
    edges = {edge['id']: edge for edge in edge_records}
    require(len(edges) == len(edge_records), 'Duplicate edge ID')
    for edge in edge_records:
        require(edge.get('label') and edge.get('kind'), f"{edge['id']}: incomplete edge")
        require(edge.get('status') in STATUSES, f"{edge['id']}: invalid evidence status")
        require(edge.get('source') in nodes and edge.get('target') in nodes,
                f"{edge['id']}: missing endpoint")
        check_sources(edge)
    flow_ids = set()
    for flow in catalog['flows']:
        require(flow['id'] not in flow_ids, 'Duplicate flow ID')
        flow_ids.add(flow['id'])
        require(flow.get('label') and flow.get('description') and flow.get('steps'),
                f"{flow['id']}: incomplete flow")
        step_ids = set()
        for step in flow['steps']:
            require(step['id'] not in step_ids, f"{flow['id']}: duplicate step")
            step_ids.add(step['id'])
            require(step.get('label') and step.get('description'),
                    f"{step['id']}: incomplete step")
            require(step.get('source') in nodes and step.get('target') in nodes,
                    f"{step['id']}: missing endpoint")
            for reference in step.get('edge_ids', []):
                require(reference in edges, f"{step['id']}: missing edge")
                linked = edges[reference]
                require(linked['source'] == step['source'] and linked['target'] == step['target'],
                        f"{step['id']}: edge endpoints do not match")
    return {
        'nodes': len(nodes), 'edges': len(edges), 'flows': len(flow_ids),
        'kinds': dict(sorted(Counter(node['kind'] for node in node_records).items())),
        'wiki_sources': len({source['page_id'] for record in node_records + edge_records
                             for source in record['sources'] if source['type'] == 'wiki'}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    try:
        report = check_catalog(json.loads(args.path.read_text(encoding='utf-8')))
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f'Invalid Atlas catalog: {error}\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
