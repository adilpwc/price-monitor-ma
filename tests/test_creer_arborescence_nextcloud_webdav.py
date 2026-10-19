#!/usr/bin/env python3
"""Crée directement une arborescence dans Nextcloud via WebDAV.

Authentification recommandée par variables d'environnement :
  export NEXTCLOUD_URL="https://cloud.exemple.fr"
  export NEXTCLOUD_USER="mon_utilisateur"
  export NEXTCLOUD_PASSWORD="mot_de_passe_application"

Puis :
  python3 creer_arborescence_nextcloud_webdav.py --simulation
  python3 creer_arborescence_nextcloud_webdav.py
"""
from __future__ import annotations
import argparse
import base64
import getpass
import os
import ssl
import sys
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ARBORESCENCE = {'00_A_CLASSER': ['Societe', 'Auto_entrepreneur', 'Personnel'],
 '01_SOCIETE': {'01_Administratif_et_Juridique': ['Creation_et_Immatriculation',
                                                  'Statuts',
                                                  'Assurances',
                                                  'Contrats_generaux',
                                                  'Courriers_officiels'],
                '02_Comptabilite': {'2026': ['01_Factures_clients',
                                             '02_Avoirs_clients',
                                             '03_Factures_fournisseurs',
                                             '04_Banque',
                                             '05_Fiscalite',
                                             '06_Notes_de_frais',
                                             '07_Echanges_comptable']},
                '03_Commercial': {'Clients': {'MODELE_Nom_client': ['Contrats',
                                                                    'Devis_et_Commandes',
                                                                    'Livrables',
                                                                    'Correspondances']},
                                  'Fournisseurs': {'MODELE_Nom_fournisseur': ['Contrats',
                                                                              'Commandes',
                                                                              'Correspondances']}},
                '04_Projets': {'MODELE_Nom_projet': ['01_Cadrage',
                                                     '02_Conception',
                                                     '03_Realisation',
                                                     '04_Tests',
                                                     '05_Livrables',
                                                     '99_Archives']},
                '05_Ressources_Humaines': ['Employes',
                                           'Prestataires',
                                           'Paie',
                                           'Conges',
                                           'Formations'],
                '06_Communication': ['Identite_visuelle',
                                     'Site_internet',
                                     'Supports_commerciaux',
                                     'Publications'],
                '99_ARCHIVES': []},
 '02_AUTO_ENTREPRENEUR': {'01_Administratif': ['Creation_et_Immatriculation',
                                               'Attestations',
                                               'Assurances',
                                               'Contrats_generaux',
                                               'Courriers_officiels'],
                          '02_Comptabilite': {'2026': ['01_Factures_clients',
                                                       '02_Avoirs_clients',
                                                       '03_Depenses_et_Achats',
                                                       '04_Banque',
                                                       '05_Declarations',
                                                       '06_Justificatifs']},
                          '03_Clients': {'MODELE_Nom_client': ['Contrats',
                                                               'Devis_et_Commandes',
                                                               'Travaux_et_Livrables',
                                                               'Correspondances']},
                          '04_Projets': {'MODELE_Nom_projet': ['Documents_de_travail',
                                                               'Livrables',
                                                               'Archives']},
                          '05_Communication': ['Identite_visuelle',
                                               'Portfolio',
                                               'Supports_commerciaux'],
                          '99_ARCHIVES': []},
 '03_PERSONNEL': {'01_Identite_et_Famille': ['Identite', 'Etat_civil', 'Photos_identite'],
                  '02_Logement': ['Contrats', 'Factures', 'Assurances', 'Travaux'],
                  '03_Banque_et_Finances': ['Comptes_bancaires',
                                            'Credits',
                                            'Epargne',
                                            'Justificatifs'],
                  '04_Impots_et_Administration': ['2025', '2026', 'Courriers'],
                  '05_Sante': ['Ordonnances', 'Analyses', 'Comptes_rendus', 'Mutuelle'],
                  '06_Vehicules': {'MODELE_Marque_Modele': ['Administratif_et_Assurance',
                                                            'Entretien',
                                                            'Factures']},
                  '07_Voyages': ['MODELE_AAAA-MM_Destination'],
                  '08_Photos_et_Videos': ['Famille', 'Evenements', 'Voyages'],
                  '09_Formations': ['Anglais', 'Informatique', 'Certifications'],
                  '99_ARCHIVES': []},
 '04_PROJETS_PERSONNELS': {'Villa': ['01_Besoins_et_Idees',
                                     '02_Plans_2D',
                                     '03_Modeles_3D',
                                     '04_Rendus',
                                     '05_Electricite',
                                     '06_Eau_et_Assainissement',
                                     '07_Devis_et_Budget',
                                     '08_Autorisations_et_Contrats',
                                     '09_Photos_du_chantier',
                                     '99_Archives'],
                           'Informatique': ['SAP_ABAP',
                                            'Nextcloud',
                                            'IA_et_Automatisation',
                                            'Scripts'],
                           'MODELE_Autre_projet': []},
 '05_MODELES': {'Societe': ['Factures', 'Devis', 'Contrats', 'Courriers'],
                'Auto_entrepreneur': ['Factures', 'Devis', 'Contrats'],
                'Personnel': []},
 '06_PARTAGE_TEMPORAIRE': ['A_envoyer', 'Recu_a_traiter'],
 '07_SAUVEGARDES_TECHNIQUES': ['Ordinateur', 'Telephone', 'Configurations', 'Exports_applications'],
 '99_ARCHIVES_GENERALES': ['Ancienne_societe', 'Anciennes_activites', 'Anciennes_sauvegardes']}

DESCRIPTIONS = {'00_A_CLASSER': 'Zone temporaire pour les nouveaux documents à ranger. Elle doit être vidée '
                 'régulièrement.',
 '01_SOCIETE': 'Documents appartenant juridiquement et comptablement à la société.',
 '02_AUTO_ENTREPRENEUR': "Documents appartenant exclusivement à l'activité d'auto-entrepreneur.",
 '03_PERSONNEL': 'Documents privés et administratifs personnels.',
 '04_PROJETS_PERSONNELS': 'Documents de travail liés aux projets personnels.',
 '05_MODELES': 'Uniquement les modèles vierges. Les exemplaires remplis doivent être classés dans '
               'leur dossier officiel.',
 '06_PARTAGE_TEMPORAIRE': 'Fichiers déposés temporairement pour envoi ou traitement. Ne pas '
                          'utiliser comme archive.',
 '07_SAUVEGARDES_TECHNIQUES': 'Copies techniques de sauvegarde, distinctes des documents de '
                              'travail originaux.',
 '99_ARCHIVES_GENERALES': 'Archives anciennes ne relevant plus des espaces actifs.',
 '01_Factures_clients': "Emplacement officiel unique des factures clients de l'année concernée.",
 '02_Avoirs_clients': "Emplacement officiel unique des avoirs clients de l'année concernée.",
 '03_Factures_fournisseurs': "Emplacement officiel unique des factures fournisseurs de l'année "
                             'concernée.',
 '03_Depenses_et_Achats': "Emplacement officiel unique des dépenses et achats de l'activité.",
 'MODELE_Nom_client': 'Dossier modèle à dupliquer puis renommer avec le nom du client. Ne pas y '
                      'copier les factures.',
 'MODELE_Nom_fournisseur': 'Dossier modèle à dupliquer puis renommer avec le nom du fournisseur. '
                           'Ne pas y copier les factures.',
 'MODELE_Nom_projet': 'Dossier modèle à dupliquer puis renommer avec le nom du projet.'}


def normaliser_enfants(noeud):
    if isinstance(noeud, dict): return noeud.items()
    if isinstance(noeud, list): return ((nom, []) for nom in noeud)
    raise TypeError(f"Structure non prise en charge : {type(noeud)!r}")

def iterer_dossiers(noeud, prefixe=PurePosixPath()):
    for nom, enfants in normaliser_enfants(noeud):
        chemin = prefixe / nom
        yield chemin
        yield from iterer_dossiers(enfants, chemin)

def contenu_readme(chemin: PurePosixPath) -> bytes:
    nom=chemin.name
    desc=DESCRIPTIONS.get(nom, f"Documents correspondant à la catégorie « {nom.replace('_',' ')} ».")
    texte=f'''# {nom.replace('_',' ')}

## Rôle du dossier

{desc}

## Emplacement

`{chemin.as_posix()}`

## Règles de classement

- Conserver chaque document original dans un seul emplacement officiel.
- Utiliser **Déplacer** plutôt que **Copier** lors du classement.
- Ne pas déposer ici une copie d'un document déjà classé ailleurs.
- Nom conseillé : `AAAA-MM-JJ_Type_Tiers_Objet.ext`.
- Pour les factures, conserver le numéro officiel dans le nom du fichier.

## Anti-doublon

Avant d'ajouter un fichier, rechercher sa référence dans Nextcloud. S'il existe déjà, utiliser le partage, les favoris ou un lien vers l'original plutôt qu'une copie.
'''
    return texte.encode('utf-8')

class WebDAV:
    def __init__(self, serveur, utilisateur, mot_de_passe, racine='', verifier_tls=True, timeout=30):
        parties=urlsplit(serveur.strip().rstrip('/'))
        if parties.scheme not in ('http','https') or not parties.netloc:
            raise ValueError("--url doit être une URL HTTP(S) valide")
        base_path=parties.path.rstrip('/')
        user_q=quote(utilisateur, safe='')
        dav_path=f"{base_path}/remote.php/dav/files/{user_q}"
        self.base=urlunsplit((parties.scheme, parties.netloc, dav_path, '', '')).rstrip('/')
        self.racine=PurePosixPath(racine.strip('/')) if racine.strip('/') else PurePosixPath()
        jeton=base64.b64encode(f"{utilisateur}:{mot_de_passe}".encode()).decode()
        self.headers={'Authorization':f'Basic {jeton}','User-Agent':'Arborescence-Nextcloud-WebDAV/2.0'}
        self.context=ssl.create_default_context() if verifier_tls else ssl._create_unverified_context()
        self.timeout=timeout

    def url(self, chemin=PurePosixPath()):
        complet=self.racine / chemin
        morceaux=[quote(p, safe='') for p in complet.parts]
        return self.base + (('/' + '/'.join(morceaux)) if morceaux else '')

    def requete(self, methode, chemin=PurePosixPath(), data=None, headers=None, acceptes=()):
        h=dict(self.headers); h.update(headers or {})
        req=Request(self.url(chemin), data=data, headers=h, method=methode)
        try:
            with urlopen(req, context=self.context, timeout=self.timeout) as rep:
                code=rep.status; contenu=rep.read()
        except HTTPError as exc:
            code=exc.code; contenu=exc.read()
        except URLError as exc:
            raise RuntimeError(f"Connexion impossible : {exc.reason}") from exc
        if code not in acceptes:
            extrait=contenu.decode('utf-8','replace')[:400].replace('\n',' ')
            raise RuntimeError(f"WebDAV {methode} {self.url(chemin)} -> HTTP {code}. {extrait}")
        return code

    def tester_connexion(self):
        # Tester la racine du compte, même si le dossier cible n'existe pas encore.
        originale=self.racine
        try:
            self.racine=PurePosixPath()
            return self.requete('PROPFIND', headers={'Depth':'0'}, acceptes=(200,207))
        finally:
            self.racine=originale

    def existe(self, chemin):
        return self.requete('PROPFIND', chemin, headers={'Depth':'0'}, acceptes=(200,207,404)) != 404

    def creer_dossier(self, chemin):
        code=self.requete('MKCOL', chemin, acceptes=(201,405))
        if code==405 and not self.existe(chemin):
            raise RuntimeError(f"Le serveur a refusé la création : {chemin}")
        return code==201

    def deposer_readme_sans_ecraser(self, dossier, contenu):
        chemin=dossier/'README.md'
        code=self.requete('PUT', chemin, data=contenu,
            headers={'Content-Type':'text/markdown; charset=utf-8','If-None-Match':'*'},
            acceptes=(201,204,412))
        return code in (201,204)

def arguments():
    p=argparse.ArgumentParser(description='Créer l’arborescence dans Nextcloud via WebDAV.')
    p.add_argument('--url', default=os.getenv('NEXTCLOUD_URL'), help='URL de l’instance Nextcloud')
    p.add_argument('--utilisateur', default=os.getenv('NEXTCLOUD_USER'), help='Identifiant Nextcloud')
    p.add_argument('--mot-de-passe', default=os.getenv('NEXTCLOUD_PASSWORD'), help=argparse.SUPPRESS)
    p.add_argument('--dossier-racine', default='Documents', help='Dossier Nextcloud contenant l’arborescence')
    p.add_argument('--simulation', action='store_true', help='Tester la connexion et afficher le plan sans créer')
    p.add_argument('--sans-verification-tls', action='store_true', help='Désactiver TLS uniquement pour un serveur de test')
    p.add_argument('--timeout', type=int, default=30)
    return p.parse_args()

def main():
    a=arguments()
    if not a.url or not a.utilisateur:
        print('ERREUR : renseigner --url et --utilisateur, ou NEXTCLOUD_URL et NEXTCLOUD_USER.',file=sys.stderr); return 2
    mdp=a.mot_de_passe or getpass.getpass('Mot de passe d’application Nextcloud : ')
    if not mdp:
        print('ERREUR : mot de passe absent.',file=sys.stderr); return 2
    try:
        client=WebDAV(a.url,a.utilisateur,mdp,a.dossier_racine,not a.sans_verification_tls,a.timeout)
        client.tester_connexion()
        dossiers=list(iterer_dossiers(ARBORESCENCE))
        print(f'Connexion WebDAV réussie. Dossier cible : /{a.dossier_racine.strip("/")}')
        print(f'Dossiers prévus : {len(dossiers)} ; README prévus : {len(dossiers)}')
        if a.simulation:
            print('[SIMULATION] Aucune modification envoyée à Nextcloud.'); return 0
        # MKCOL exige que chaque parent existe : création séquentielle.
        if client.racine and not client.existe(PurePosixPath()):
            # Crée chaque segment éventuel de la racine distante.
            courant=PurePosixPath(); originale=client.racine; client.racine=PurePosixPath()
            for part in originale.parts:
                courant/=part; client.creer_dossier(courant)
            client.racine=originale
        stats={'dc':0,'de':0,'rc':0,'re':0}
        for chemin in dossiers:
            if client.creer_dossier(chemin): stats['dc']+=1
            else: stats['de']+=1
            if client.deposer_readme_sans_ecraser(chemin,contenu_readme(chemin)): stats['rc']+=1
            else: stats['re']+=1
        print(f"Dossiers créés : {stats['dc']} ; déjà présents : {stats['de']}")
        print(f"README créés : {stats['rc']} ; déjà présents et conservés : {stats['re']}")
        return 0
    except (ValueError,RuntimeError) as exc:
        print(f'ERREUR : {exc}',file=sys.stderr); return 1

if __name__=='__main__': raise SystemExit(main())
