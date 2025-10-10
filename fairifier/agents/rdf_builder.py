"""RDF builder agent for generating RDF graphs and RO-Crate metadata."""

import json
from datetime import datetime
from typing import Dict, Any, List
from urllib.parse import quote
from rdflib import Graph, Namespace, Literal, URIRef, BNode
from rdflib.namespace import RDF, RDFS, DCTERMS, FOAF, XSD

from .base import BaseAgent
from ..models import FAIRifierState
from ..config import config


class RDFBuilderAgent(BaseAgent):
    """Agent for building RDF graphs and RO-Crate metadata."""
    
    def __init__(self):
        super().__init__("RDFBuilder")
        
        # Define namespaces
        self.PROV = Namespace("http://www.w3.org/ns/prov#")
        self.SCHEMA = Namespace("https://schema.org/")
        self.MIXS = Namespace("http://w3id.org/mixs/")
        self.ENVO = Namespace("http://purl.obolibrary.org/obo/ENVO_")
        self.FAIRIFIER = Namespace("http://fairifier.org/")
        
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Build RDF graph and RO-Crate from metadata fields."""
        self.log_execution(state, "Starting RDF building")
        
        try:
            doc_info = state["document_info"]
            metadata_fields = state["metadata_fields"]
            
            # Create RDF graph
            graph = self._create_rdf_graph(doc_info, metadata_fields)
            
            # Serialize to different formats
            turtle_rdf = graph.serialize(format='turtle')
            jsonld_rdf = graph.serialize(format='json-ld', indent=2)
            
            # Create RO-Crate metadata
            ro_crate = self._create_ro_crate(doc_info, metadata_fields)
            
            # Store in artifacts
            if "artifacts" not in state:
                state["artifacts"] = {}
            
            state["artifacts"]["rdf_turtle"] = turtle_rdf
            state["artifacts"]["rdf_jsonld"] = jsonld_rdf
            state["artifacts"]["ro_crate"] = json.dumps(ro_crate, indent=2)
            
            # Store graph for validation
            state["rdf_graph"] = turtle_rdf
            
            # Calculate confidence
            confidence = self._calculate_building_confidence(graph, metadata_fields)
            self.update_confidence(state, "rdf_building", confidence)
            
            self.log_execution(
                state,
                f"RDF building completed. Graph has {len(graph)} triples, "
                f"confidence={confidence:.2f}"
            )
            
        except Exception as e:
            self.log_execution(state, f"RDF building failed: {str(e)}", "error")
            self.update_confidence(state, "rdf_building", 0.0)
        
        return state
    
    def _create_rdf_graph(self, doc_info: Dict[str, Any], metadata_fields: List[Dict[str, Any]]) -> Graph:
        """Create RDF graph from document info and metadata fields."""
        g = Graph()
        
        # Bind namespaces
        g.bind("prov", self.PROV)
        g.bind("schema", self.SCHEMA)
        g.bind("mixs", self.MIXS)
        g.bind("envo", self.ENVO)
        g.bind("fairifier", self.FAIRIFIER)
        g.bind("dcterms", DCTERMS)
        g.bind("foaf", FOAF)
        
        # Create main dataset URI
        dataset_uri = self.FAIRIFIER[f"dataset/{self._safe_name(doc_info.get('title', 'dataset'))}"]
        
        # Dataset metadata
        g.add((dataset_uri, RDF.type, self.SCHEMA.Dataset))
        g.add((dataset_uri, DCTERMS.title, Literal(doc_info.get('title', 'Research Dataset'))))
        
        if doc_info.get('abstract'):
            g.add((dataset_uri, DCTERMS.description, Literal(doc_info['abstract'])))
        
        # Authors
        for i, author in enumerate(doc_info.get('authors', [])):
            author_uri = self.FAIRIFIER[f"person/{self._safe_name(author)}"]
            g.add((author_uri, RDF.type, self.SCHEMA.Person))
            g.add((author_uri, FOAF.name, Literal(author)))
            g.add((dataset_uri, self.SCHEMA.author, author_uri))
        
        # Keywords
        for keyword in doc_info.get('keywords', []):
            g.add((dataset_uri, self.SCHEMA.keywords, Literal(keyword)))
        
        # Research domain
        if doc_info.get('research_domain'):
            g.add((dataset_uri, self.SCHEMA.about, Literal(doc_info['research_domain'])))
        
        # Add metadata fields as properties
        for field in metadata_fields:
            self._add_metadata_field_to_graph(g, dataset_uri, field)
        
        # Add provenance information
        self._add_provenance_info(g, dataset_uri)
        
        return g
    
    def _add_metadata_field_to_graph(self, graph: Graph, dataset_uri: URIRef, field: Dict[str, Any]) -> None:
        """Add a metadata field to the RDF graph."""
        field_name = field["name"]
        
        # Create property URI
        if field.get("ontology_term"):
            # Use ontology term if available
            prop_uri = URIRef(field["ontology_term"])
        else:
            # Create MIXS property URI
            prop_uri = self.MIXS[field_name]
        
        # Add property definition
        graph.add((prop_uri, RDF.type, RDF.Property))
        graph.add((prop_uri, RDFS.label, Literal(field_name)))
        graph.add((prop_uri, RDFS.comment, Literal(field["description"])))
        
        # Add example value if available
        if field.get("example_value"):
            value = self._convert_value_to_rdf(field["example_value"], field["data_type"])
            graph.add((dataset_uri, prop_uri, value))
        
        # Add evidence if available
        if field.get("evidence_text"):
            evidence_node = BNode()
            graph.add((dataset_uri, self.PROV.wasAttributedTo, evidence_node))
            graph.add((evidence_node, RDF.type, self.PROV.Entity))
            graph.add((evidence_node, RDFS.label, Literal(f"Evidence for {field_name}")))
            graph.add((evidence_node, self.PROV.value, Literal(field["evidence_text"])))
    
    def _convert_value_to_rdf(self, value: Any, data_type: str) -> Literal:
        """Convert a value to appropriate RDF literal."""
        if data_type == "number":
            try:
                if '.' in str(value):
                    return Literal(float(value), datatype=XSD.decimal)
                else:
                    return Literal(int(value), datatype=XSD.integer)
            except ValueError:
                return Literal(str(value))
        elif data_type == "datetime":
            return Literal(value, datatype=XSD.dateTime)
        else:
            return Literal(str(value))
    
    def _add_provenance_info(self, graph: Graph, dataset_uri: URIRef) -> None:
        """Add provenance information to the graph."""
        # Generation activity
        generation_uri = self.FAIRIFIER[f"activity/generation/{datetime.now().strftime('%Y%m%d_%H%M%S')}"]
        graph.add((generation_uri, RDF.type, self.PROV.Activity))
        graph.add((generation_uri, RDFS.label, Literal("FAIRifier metadata generation")))
        graph.add((generation_uri, self.PROV.startedAtTime, Literal(datetime.now(), datatype=XSD.dateTime)))
        
        # Agent (FAIRifier system)
        agent_uri = self.FAIRIFIER["agent/fairifier"]
        graph.add((agent_uri, RDF.type, self.PROV.SoftwareAgent))
        graph.add((agent_uri, FOAF.name, Literal("FAIRifier Agentic Framework")))
        graph.add((agent_uri, self.SCHEMA.version, Literal("0.1.0")))
        
        # Connect dataset to generation
        graph.add((dataset_uri, self.PROV.wasGeneratedBy, generation_uri))
        graph.add((generation_uri, self.PROV.wasAssociatedWith, agent_uri))
    
    def _create_ro_crate(self, doc_info: Dict[str, Any], metadata_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create RO-Crate metadata."""
        ro_crate = {
            "@context": [
                "https://w3id.org/ro/crate/1.1/context",
                {
                    "mixs": "http://w3id.org/mixs/",
                    "envo": "http://purl.obolibrary.org/obo/ENVO_"
                }
            ],
            "@graph": []
        }
        
        # Root dataset
        root_dataset = {
            "@id": "./",
            "@type": "Dataset",
            "name": doc_info.get('title', 'Research Dataset'),
            "description": doc_info.get('abstract', ''),
            "dateCreated": datetime.now().isoformat(),
            "creator": [],
            "keywords": doc_info.get('keywords', []),
            "about": doc_info.get('research_domain', ''),
            "hasPart": []
        }
        
        # Add authors
        for author in doc_info.get('authors', []):
            author_id = f"#person-{self._safe_name(author)}"
            root_dataset["creator"].append({"@id": author_id})
            
            # Add person entity
            person = {
                "@id": author_id,
                "@type": "Person",
                "name": author
            }
            ro_crate["@graph"].append(person)
        
        # Add metadata template file
        template_file = {
            "@id": "template.yaml",
            "@type": "File",
            "name": "Metadata Template",
            "description": "YAML template for metadata collection",
            "encodingFormat": "application/yaml",
            "conformsTo": "MIxS"
        }
        root_dataset["hasPart"].append({"@id": "template.yaml"})
        ro_crate["@graph"].append(template_file)
        
        # Add RDF file
        rdf_file = {
            "@id": "metadata.ttl",
            "@type": "File", 
            "name": "RDF Metadata",
            "description": "Metadata in RDF Turtle format",
            "encodingFormat": "text/turtle",
            "conformsTo": ["http://www.w3.org/ns/prov#", "https://schema.org/"]
        }
        root_dataset["hasPart"].append({"@id": "metadata.ttl"})
        ro_crate["@graph"].append(rdf_file)
        
        # Add generation provenance
        generation = {
            "@id": "#generation",
            "@type": "CreateAction",
            "name": "Metadata generation",
            "description": "Automated generation of FAIR metadata using FAIRifier",
            "startTime": datetime.now().isoformat(),
            "instrument": {
                "@id": "#fairifier"
            },
            "result": {"@id": "./"}
        }
        ro_crate["@graph"].append(generation)
        
        # Add FAIRifier as instrument
        fairifier = {
            "@id": "#fairifier",
            "@type": "SoftwareApplication",
            "name": "FAIRifier Agentic Framework",
            "version": "0.1.0",
            "description": "Automated FAIR metadata generation system"
        }
        ro_crate["@graph"].append(fairifier)
        
        ro_crate["@graph"].append(root_dataset)
        
        return ro_crate
    
    def _safe_name(self, name: str) -> str:
        """Convert name to URL-safe format."""
        return quote(name.lower().replace(' ', '_').replace(':', '_'))
    
    def _calculate_building_confidence(self, graph: Graph, metadata_fields: List[Dict[str, Any]]) -> float:
        """Calculate confidence for RDF building."""
        # Base score from graph size
        triple_count = len(graph)
        base_score = min(triple_count / 50.0, 0.4)
        
        # Score from metadata fields with values
        fields_with_values = sum(1 for f in metadata_fields if f.get("example_value"))
        value_score = min(fields_with_values / 10.0, 0.3)
        
        # Score from ontology terms
        fields_with_ontology = sum(1 for f in metadata_fields if f.get("ontology_term"))
        ontology_score = min(fields_with_ontology / 5.0, 0.3)
        
        return min(base_score + value_score + ontology_score, 1.0)
