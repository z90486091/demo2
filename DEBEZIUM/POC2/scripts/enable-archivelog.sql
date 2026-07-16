-- ARCHIVELOG mode (required for LogMiner) — one-time, CDB level
SHUTDOWN IMMEDIATE;
STARTUP MOUNT;
ALTER DATABASE ARCHIVELOG;
ALTER DATABASE OPEN;

-- Supplemental logging (required for LogMiner) — one-time, CDB level
ALTER DATABASE ADD SUPPLEMENTAL LOG DATA;

ARCHIVE LOG LIST;