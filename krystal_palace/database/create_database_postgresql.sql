-- ══════════════════════════════════════════════════════════════════════════════
-- create_database_postgresql.sql — Krystal Palace Hôtel Yaoundé v7
-- Exécuter dans pgAdmin 4 avant de lancer le serveur
-- ══════════════════════════════════════════════════════════════════════════════

-- ÉTAPE 1 : exécuter en tant que superuser "postgres" dans pgAdmin
CREATE USER krystal_user WITH PASSWORD 'krystal2024';
CREATE DATABASE krystal_palace OWNER krystal_user ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE krystal_palace TO krystal_user;

-- ÉTAPE 2 : se connecter à la base krystal_palace puis exécuter :

CREATE TABLE IF NOT EXISTS clients (
    id          SERIAL PRIMARY KEY,
    nom         VARCHAR(100) NOT NULL,
    prenom      VARCHAR(100) NOT NULL,
    cni         VARCHAR(50)  NOT NULL UNIQUE,
    telephone   VARCHAR(25)  NOT NULL,
    email       VARCHAR(150),
    nationalite VARCHAR(80),
    cree_le     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reservations (
    id                SERIAL PRIMARY KEY,
    ref               VARCHAR(30)  NOT NULL UNIQUE,
    client_id         INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    client_nom        VARCHAR(200) NOT NULL,
    type_chambre      VARCHAR(50)  NOT NULL,
    ref_chambre       VARCHAR(20)  NOT NULL DEFAULT 'A attribuer',
    ref_climatisation VARCHAR(20),
    arrivee           DATE         NOT NULL,
    depart            DATE         NOT NULL,
    nuits             INTEGER      NOT NULL,
    total             INTEGER      NOT NULL,
    montant_rembourse INTEGER      DEFAULT 0,
    observations      TEXT,
    statut            VARCHAR(30)  NOT NULL DEFAULT 'Confirmee',
    paiement_sim      BOOLEAN      DEFAULT FALSE,
    paiement_mode     VARCHAR(50),
    paiement_statut   VARCHAR(50)  NOT NULL DEFAULT 'En attente',
    reference_om      VARCHAR(60),
    facture_pdf       TEXT,
    cree_le           TIMESTAMP    DEFAULT NOW(),
    modifie_le        TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS annulations (
    id               SERIAL PRIMARY KEY,
    reservation_id   INTEGER REFERENCES reservations(id) ON DELETE CASCADE,
    ref              VARCHAR(30) NOT NULL,
    date_annulation  TIMESTAMP DEFAULT NOW(),
    jours_penalite   INTEGER NOT NULL DEFAULT 0,
    taux_penalite    NUMERIC(5,2) NOT NULL DEFAULT 0,
    montant_penalite INTEGER NOT NULL DEFAULT 0,
    montant_rembourse INTEGER NOT NULL DEFAULT 0,
    motif            TEXT
);

CREATE TABLE IF NOT EXISTS modifications (
    id              SERIAL PRIMARY KEY,
    reservation_id  INTEGER REFERENCES reservations(id) ON DELETE CASCADE,
    ref             VARCHAR(30) NOT NULL,
    date_modif      TIMESTAMP DEFAULT NOW(),
    ancien_arrivee  DATE,
    nouvel_arrivee  DATE,
    ancien_depart   DATE,
    nouvel_depart   DATE,
    ancien_total    INTEGER,
    nouveau_total   INTEGER,
    observations    TEXT
);

CREATE INDEX IF NOT EXISTS idx_res_statut  ON reservations(statut);
CREATE INDEX IF NOT EXISTS idx_res_arrivee ON reservations(arrivee);
CREATE INDEX IF NOT EXISTS idx_res_ref     ON reservations(ref);
CREATE INDEX IF NOT EXISTS idx_cli_cni     ON clients(cni);

-- Vérification
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' ORDER BY table_name;
