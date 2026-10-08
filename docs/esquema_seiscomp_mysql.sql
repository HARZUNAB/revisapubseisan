-- ============================================================================
-- esquema_seiscomp_mysql.sql
-- Modelo relacional (subconjunto) de la base de SeisComp que usa RevisaPubSeisan.
--
-- QUÉ ES
--   Un script DDL en dialecto MySQL (InnoDB) con las tablas que consulta la
--   aplicación, sus claves y sus relaciones, pensado para VISUALIZAR el modelo.
--
-- CÓMO ABRIRLO EN MYSQL WORKBENCH
--   File -> Import -> Reverse Engineer MySQL Create Script...
--   (y elegir este archivo). Workbench arma con eso el diagrama EER.
--   Alternativa: Database -> Reverse Engineer sobre una base MySQL donde se
--   haya corrido este script.
--
-- AVISOS IMPORTANTES
--   * La base real de SeisComp es PostgreSQL; esto es una adaptación a MySQL
--     solo para el diagrama. NO es el esquema exacto de tipos de la base real.
--   * Se incluyen las columnas que USA la app (no todas las de SeisComp).
--   * En la base real, `_parent_oid` es una FK genérica a `object._oid`. Acá se
--     dibuja como FK a la tabla PADRE concreta (network->station, origin->
--     arrival, etc.) para que el diagrama sea legible. Igual para los enlaces
--     por id público: en la base son referencias de texto resueltas con
--     `publicobject`, y acá se declaran como FK a `publicobject.m_publicid`.
--   * `origin._parent_oid` NO enlaza con `event` en esta base (0 coincidencias);
--     el evento se une a su origen PREFERIDO por `m_preferredoriginid`.
--
-- Autor: RevisaPubSeisan. Ver también docs/esquema_seiscomp.md.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS seiscomp2
    DEFAULT CHARACTER SET utf8mb4;
USE seiscomp2;

SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------------
-- Modelo de identidad
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS configstation;
DROP TABLE IF EXISTS configmodule;
DROP TABLE IF EXISTS stream;
DROP TABLE IF EXISTS sensorlocation;
DROP TABLE IF EXISTS station;
DROP TABLE IF EXISTS network;
DROP TABLE IF EXISTS stationmagnitudecontribution;
DROP TABLE IF EXISTS stationmagnitude;
DROP TABLE IF EXISTS amplitude;
DROP TABLE IF EXISTS pick;
DROP TABLE IF EXISTS arrival;
DROP TABLE IF EXISTS magnitude;
DROP TABLE IF EXISTS origin;
DROP TABLE IF EXISTS eventdescription;
DROP TABLE IF EXISTS event;
DROP TABLE IF EXISTS publicobject;
DROP TABLE IF EXISTS object;

CREATE TABLE object (
    _oid        BIGINT       NOT NULL COMMENT 'Clave interna del objeto SeisComp',
    _timestamp  DATETIME(6)  NULL     COMMENT 'Marca de tiempo del objeto',
    PRIMARY KEY (_oid)
) ENGINE=InnoDB COMMENT='Tabla base de toda la jerarquía de objetos de SeisComp';

CREATE TABLE publicobject (
    _oid        BIGINT       NOT NULL COMMENT 'Mismo _oid del objeto',
    m_publicid  VARCHAR(255) NOT NULL COMMENT 'Identificador público en texto (p. ej. Origin/..., Pick/...)',
    PRIMARY KEY (_oid),
    UNIQUE KEY uq_publicobject_publicid (m_publicid),
    CONSTRAINT fk_publicobject_object FOREIGN KEY (_oid)
        REFERENCES object (_oid)
) ENGINE=InnoDB COMMENT='Puente entre el _oid interno y el id público (texto)';

-- ---------------------------------------------------------------------------
-- Solución sísmica
-- ---------------------------------------------------------------------------
CREATE TABLE event (
    _oid                     BIGINT       NOT NULL,
    m_preferredoriginid      VARCHAR(255) NULL COMMENT 'Id público del origen preferido',
    m_preferredmagnitudeid   VARCHAR(255) NULL COMMENT 'Id público de la magnitud preferida',
    m_type                   VARCHAR(40)  NULL COMMENT 'Tipo de evento',
    PRIMARY KEY (_oid),
    CONSTRAINT fk_event_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_event_preferredorigin FOREIGN KEY (m_preferredoriginid)
        REFERENCES publicobject (m_publicid),
    CONSTRAINT fk_event_preferredmagnitude FOREIGN KEY (m_preferredmagnitudeid)
        REFERENCES publicobject (m_publicid)
) ENGINE=InnoDB COMMENT='Evento. No guarda lat/lon/hora: eso vive en origin';

CREATE TABLE eventdescription (
    _oid         BIGINT       NOT NULL,
    _parent_oid  BIGINT       NULL COMMENT 'Evento padre',
    m_text       TEXT         NULL COMMENT 'Texto de la descripción',
    m_type       VARCHAR(80)  NULL COMMENT 'Tipo (la región es m_type = ''region name'')',
    PRIMARY KEY (_oid),
    CONSTRAINT fk_eventdescription_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_eventdescription_event FOREIGN KEY (_parent_oid)
        REFERENCES event (_oid)
) ENGINE=InnoDB COMMENT='Descripción del evento (de acá sale la región)';

CREATE TABLE origin (
    _oid                        BIGINT       NOT NULL,
    _parent_oid                 BIGINT       NULL COMMENT 'No enlaza con event en esta base (ver cabecera)',
    m_time_value                DATETIME(6)  NULL COMMENT 'Hora origen',
    m_latitude_value            DOUBLE       NULL,
    m_longitude_value           DOUBLE       NULL,
    m_depth_value               DOUBLE       NULL,
    m_quality_usedphasecount    INT          NULL COMMENT 'Fases usadas',
    m_quality_standarderror     DOUBLE       NULL COMMENT 'RMS',
    m_quality_azimuthalgap      DOUBLE       NULL COMMENT 'AzGap',
    m_creationinfo_agencyid     VARCHAR(80)  NULL,
    m_creationinfo_author       VARCHAR(80)  NULL COMMENT 'Operador/analista',
    m_evaluationstatus          VARCHAR(40)  NULL COMMENT 'P. ej. confirmed',
    PRIMARY KEY (_oid),
    CONSTRAINT fk_origin_object FOREIGN KEY (_oid) REFERENCES object (_oid)
) ENGINE=InnoDB COMMENT='Solución hipocentral (origen)';

CREATE TABLE magnitude (
    _oid                     BIGINT       NOT NULL,
    _parent_oid              BIGINT       NULL COMMENT 'Origen padre',
    m_magnitude_value        DOUBLE       NULL,
    m_type                   VARCHAR(40)  NULL,
    m_creationinfo_agencyid  VARCHAR(80)  NULL,
    m_creationinfo_author    VARCHAR(80)  NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_magnitude_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_magnitude_origin FOREIGN KEY (_parent_oid)
        REFERENCES origin (_oid)
) ENGINE=InnoDB COMMENT='Magnitud de un origen';

-- ---------------------------------------------------------------------------
-- Lecturas y magnitudes por estación
-- ---------------------------------------------------------------------------
CREATE TABLE pick (
    _oid                          BIGINT       NOT NULL,
    _parent_oid                   BIGINT       NULL,
    m_time_value                  DATETIME(6)  NULL COMMENT 'Hora de la lectura',
    m_time_value_ms               INT          NULL COMMENT 'Microsegundos (0-999999)',
    m_waveformID_networkCode      VARCHAR(20)  NULL,
    m_waveformID_stationCode      VARCHAR(20)  NULL,
    m_waveformID_locationCode     VARCHAR(20)  NULL,
    m_waveformID_channelCode      VARCHAR(20)  NULL,
    m_evaluationmode              VARCHAR(20)  NULL COMMENT 'manual / automatic',
    m_creationinfo_author         VARCHAR(80)  NULL COMMENT 'Analista o daemon',
    m_creationinfo_agencyid       VARCHAR(80)  NULL,
    m_methodID                    VARCHAR(80)  NULL COMMENT 'Método del autopicker (p. ej. AIC)',
    m_polarity                    VARCHAR(20)  NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_pick_object FOREIGN KEY (_oid) REFERENCES object (_oid)
) ENGINE=InnoDB COMMENT='Lectura (pick) de una fase en una estación';

CREATE TABLE arrival (
    _oid            BIGINT       NOT NULL,
    _parent_oid     BIGINT       NULL COMMENT 'Origen padre',
    m_pickID        VARCHAR(255) NULL COMMENT 'Id público del pick',
    m_phase_code    VARCHAR(20)  NULL COMMENT 'P / S / ...',
    m_timeUsed      TINYINT      NULL COMMENT 'Si entró a la solución',
    m_weight        DOUBLE       NULL,
    m_timeResidual  DOUBLE       NULL,
    m_azimuth       DOUBLE       NULL,
    m_distance      DOUBLE       NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_arrival_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_arrival_origin FOREIGN KEY (_parent_oid) REFERENCES origin (_oid),
    CONSTRAINT fk_arrival_pick FOREIGN KEY (m_pickID)
        REFERENCES publicobject (m_publicid)
) ENGINE=InnoDB COMMENT='Llegada (fase) asociada a un origen';

CREATE TABLE amplitude (
    _oid                        BIGINT       NOT NULL,
    _parent_oid                 BIGINT       NULL,
    m_pickID                    VARCHAR(255) NULL COMMENT 'Id público del pick',
    m_snr                       DOUBLE       NULL,
    m_creationInfo_creationTime DATETIME(6)  NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_amplitude_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_amplitude_pick FOREIGN KEY (m_pickID)
        REFERENCES publicobject (m_publicid)
) ENGINE=InnoDB COMMENT='Amplitud medida sobre un pick';

CREATE TABLE stationmagnitude (
    _oid                        BIGINT       NOT NULL,
    _parent_oid                 BIGINT       NULL COMMENT 'Origen padre (NO la magnitud)',
    m_amplitudeID               VARCHAR(255) NULL COMMENT 'Id público de la amplitud',
    m_waveformID_networkCode    VARCHAR(20)  NULL,
    m_waveformID_stationCode    VARCHAR(20)  NULL,
    m_magnitude_value           DOUBLE       NULL,
    m_type                      VARCHAR(40)  NULL,
    m_passedQC                  TINYINT      NULL COMMENT 'Aprobado/rechazado por QC',
    m_creationInfo_creationTime DATETIME(6)  NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_stationmagnitude_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_stationmagnitude_origin FOREIGN KEY (_parent_oid)
        REFERENCES origin (_oid),
    CONSTRAINT fk_stationmagnitude_amplitude FOREIGN KEY (m_amplitudeID)
        REFERENCES publicobject (m_publicid)
) ENGINE=InnoDB COMMENT='Magnitud calculada por una estación para un origen';

CREATE TABLE stationmagnitudecontribution (
    _oid                   BIGINT       NOT NULL,
    _parent_oid            BIGINT       NULL COMMENT 'Magnitud preferida',
    m_stationMagnitudeID   VARCHAR(255) NULL COMMENT 'Id público de la stationmagnitude',
    m_residual             DOUBLE       NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_smc_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_smc_magnitude FOREIGN KEY (_parent_oid) REFERENCES magnitude (_oid),
    CONSTRAINT fk_smc_stationmagnitude FOREIGN KEY (m_stationMagnitudeID)
        REFERENCES publicobject (m_publicid)
) ENGINE=InnoDB COMMENT='Aporte de una stationmagnitude a la magnitud preferida';

-- ---------------------------------------------------------------------------
-- Inventario
-- ---------------------------------------------------------------------------
CREATE TABLE network (
    _oid       BIGINT      NOT NULL,
    m_code     VARCHAR(20) NULL,
    m_start    DATETIME    NULL COMMENT 'Inicio de vigencia',
    m_end      DATETIME    NULL COMMENT 'Fin de vigencia (NULL = abierta)',
    m_start_ms INT         NULL,
    m_end_ms   INT         NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_network_object FOREIGN KEY (_oid) REFERENCES object (_oid)
) ENGINE=InnoDB COMMENT='Red';

CREATE TABLE station (
    _oid         BIGINT       NOT NULL,
    _parent_oid  BIGINT       NULL COMMENT 'Red padre',
    m_code       VARCHAR(20)  NULL,
    m_start      DATETIME     NULL,
    m_end        DATETIME     NULL,
    m_latitude   DOUBLE       NULL,
    m_longitude  DOUBLE       NULL,
    m_elevation  DOUBLE       NULL,
    m_place      VARCHAR(120) NULL,
    m_country    VARCHAR(80)  NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_station_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_station_network FOREIGN KEY (_parent_oid) REFERENCES network (_oid)
) ENGINE=InnoDB COMMENT='Estación, hija de la red';

CREATE TABLE sensorlocation (
    _oid         BIGINT      NOT NULL,
    _parent_oid  BIGINT      NULL COMMENT 'Estación padre',
    m_code       VARCHAR(20) NULL COMMENT 'Location code',
    m_start      DATETIME    NULL,
    m_end        DATETIME    NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_sensorlocation_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_sensorlocation_station FOREIGN KEY (_parent_oid)
        REFERENCES station (_oid)
) ENGINE=InnoDB COMMENT='Sensor location (código de ubicación)';

CREATE TABLE stream (
    _oid         BIGINT      NOT NULL,
    _parent_oid  BIGINT      NULL COMMENT 'Sensor location padre',
    m_code       VARCHAR(20) NULL COMMENT 'Canal (p. ej. BHZ)',
    m_start      DATETIME    NULL,
    m_end        DATETIME    NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_stream_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_stream_sensorlocation FOREIGN KEY (_parent_oid)
        REFERENCES sensorlocation (_oid)
) ENGINE=InnoDB COMMENT='Canal/stream, hijo del sensor location';

-- ---------------------------------------------------------------------------
-- Configuración (bindings)
-- ---------------------------------------------------------------------------
CREATE TABLE configmodule (
    _oid       BIGINT      NOT NULL,
    m_name     VARCHAR(80) NULL COMMENT 'En esta base hay uno solo: trunk',
    m_enabled  TINYINT     NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_configmodule_object FOREIGN KEY (_oid) REFERENCES object (_oid)
) ENGINE=InnoDB COMMENT='Módulo de configuración de SeisComp';

CREATE TABLE configstation (
    _oid           BIGINT      NOT NULL,
    _parent_oid    BIGINT      NULL COMMENT 'Módulo padre',
    m_networkcode  VARCHAR(20) NULL,
    m_stationcode  VARCHAR(20) NULL,
    m_enabled      TINYINT     NULL,
    PRIMARY KEY (_oid),
    CONSTRAINT fk_configstation_object FOREIGN KEY (_oid) REFERENCES object (_oid),
    CONSTRAINT fk_configstation_module FOREIGN KEY (_parent_oid)
        REFERENCES configmodule (_oid)
) ENGINE=InnoDB COMMENT='Binding de estación: lo que SeisComp está configurado a procesar';

SET FOREIGN_KEY_CHECKS = 1;

-- Fin del modelo.
