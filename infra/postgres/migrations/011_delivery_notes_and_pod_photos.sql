-- 011 · Delivery notes and proof-of-delivery photos (issue #25)
--
-- The two unstructured datasets of the phase 2 classification.
--
-- 1. bronze.delivery_notes: the AI-generated corpus of prompt 008, the free text recipients type
--    for the driver, with the labels the generating model gave each note. Loaded by
--    load-reference from a Parquet file in the RustFS bronze bucket, like the fleet register.
-- 2. bronze.orders.note_id: the note an order carries. The text stays in bronze.orders.notes as
--    the recipient typed it; note_id says which note of the corpus it is, so its labels can be
--    joined. Event tables have no foreign keys to reference data (migration 003); silver tests
--    the relationship.
-- 3. The data sources: the corpus is registered, the orders and the photos are described as they
--    are now. The photos are synthetic placeholders drawn by code, not photographs and not
--    AI-generated images, with real EXIF metadata: delivery time and position.
--
-- Bronze stays raw: no CHECK constraints (migration 007).

-- 1 · Delivery notes corpus -------------------------------------------------------------------

CREATE TABLE bronze.delivery_notes (
    note_id                text PRIMARY KEY,
    text                   text,
    language               text,
    category               text,
    likely_longer_stop     boolean,
    likely_failed_attempt  boolean,
    source                 text NOT NULL REFERENCES ops.data_sources,
    ingested_at            timestamptz NOT NULL DEFAULT now(),
    raw_object_key         text
);
COMMENT ON TABLE bronze.delivery_notes IS '{"owner": "operations", "schema_version": 1}';
COMMENT ON COLUMN bronze.delivery_notes.text IS 'The note as the recipient types it in the "notes for the driver" box. Unstructured: no fields, several languages, abbreviations and typos.';
COMMENT ON COLUMN bronze.delivery_notes.language IS 'es, ca, en, fr, it or mixed, as labelled by the generating model (prompt 008).';
COMMENT ON COLUMN bronze.delivery_notes.category IS 'Main situation of the note, as labelled by the generating model: access, schedule, neighbour or concierge, business hours, call before, pets or children, fragile or special handling, location hint, contradictory or other.';
COMMENT ON COLUMN bronze.delivery_notes.likely_longer_stop IS 'Label of the generating model: the note is likely to make the stop longer.';
COMMENT ON COLUMN bronze.delivery_notes.likely_failed_attempt IS 'Label of the generating model: the note makes a failed first attempt more likely.';
COMMENT ON COLUMN bronze.delivery_notes.raw_object_key IS 'Key of the corpus''s Parquet file in the RustFS bronze bucket.';

-- 2 · The note of each order ------------------------------------------------------------------

ALTER TABLE bronze.orders ADD COLUMN note_id text;
COMMENT ON TABLE bronze.orders IS '{"owner": "operations", "schema_version": 4}';
COMMENT ON COLUMN bronze.orders.note_id IS 'The note of bronze.delivery_notes whose text is in notes; NULL when the order carries no note.';
COMMENT ON COLUMN bronze.orders.notes IS 'Free-text delivery instructions written by the recipient, as typed. Unstructured. For generated orders, the text of the note in note_id.';
COMMENT ON COLUMN bronze.delivery_events.pod_object_key IS 'Key of the proof-of-delivery photo in the RustFS bronze bucket, pod/<service date>/<order id>.jpg: a JPEG whose EXIF metadata holds the time (DateTimeOriginal) and position (GPS) of the delivery.';

-- 3 · Data sources ----------------------------------------------------------------------------

INSERT INTO ops.data_sources (source_id, kind, provider, description, license, url) VALUES
    ('generator/delivery-notes', 'ai-generated', 'Llobregat Express generator',
     'Corpus of 300 free-text delivery notes with language, category and two labels '
     '(services/generator/seed/delivery_notes.json, prompt 008)',
     'MIT, this repository', 'prompts/008-delivery-notes.md');

UPDATE ops.data_sources
SET description = 'Orders drawn from the demand model (prompt 004) at real addresses from Open Data BCN and ICGC, '
                  'one Parquet file per service date; about a third carry a delivery note of prompt 008'
WHERE source_id = 'generator/orders';
UPDATE ops.data_sources
SET description = 'Proof-of-delivery photos: synthetic placeholder JPEGs drawn by code, not photographs, with the '
                  'delivery time and position in their EXIF metadata, under pod/ in the RustFS bronze bucket',
    url = 'services/generator/README.md'
WHERE source_id = 'simulator/pod-photos';
