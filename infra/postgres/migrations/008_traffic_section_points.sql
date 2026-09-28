-- 008 · Traffic sections in the long CSV format
--
-- Open Data BCN publishes the street sections of the trams traffic feed in two layouts.
-- transit_relacio_trams.csv packs a whole polyline, 2 to 38 points, into one text field;
-- transit_relacio_trams_format_long.csv has one row per point. The platform loads the long
-- format, so every value has its own column and nothing has to be split later.
-- bronze.traffic_sections held the packed layout and was never loaded, so it is replaced.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM bronze.traffic_sections) THEN
        RAISE EXCEPTION 'bronze.traffic_sections has rows; move them to the long format before dropping it';
    END IF;
END
$$;
DROP TABLE bronze.traffic_sections;

CREATE TABLE bronze.traffic_section_points (
    section_id      integer NOT NULL,
    point_seq       smallint NOT NULL,
    description     text,
    lon             double precision,
    lat             double precision,
    source          text NOT NULL REFERENCES ops.data_sources,
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    raw_object_key  text,
    PRIMARY KEY (section_id, point_seq)
);
COMMENT ON TABLE bronze.traffic_section_points IS '{"owner": "platform", "schema_version": 1}';
COMMENT ON COLUMN bronze.traffic_section_points.section_id IS 'Tram: section id, the value traffic_state.feed_item_id holds when feed = trams.';
COMMENT ON COLUMN bronze.traffic_section_points.point_seq IS 'Tram_Components: position of the point along the section, from 1.';
COMMENT ON COLUMN bronze.traffic_section_points.description IS 'Descripció: street and direction of the section, repeated on each of its points.';
COMMENT ON COLUMN bronze.traffic_section_points.lon IS 'Longitud, WGS84.';
COMMENT ON COLUMN bronze.traffic_section_points.lat IS 'Latitud, WGS84.';

UPDATE ops.data_sources
SET description = 'Geometry of the street sections of the trams feed, one row per point (long-format CSV)'
WHERE source_id = 'opendata-bcn/transit-relacio-trams';
