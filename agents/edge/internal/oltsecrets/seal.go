// Package oltsecrets is the Edge side of ADR-0045: OLT credentials typed in the Cloud screen arrive SEALED to a key that only this host holds, are authenticated with
// the Cloud's pinned signature key, and end up in the per-OLT credentials file. This file is the cryptographic contract (interoperable Go <-> WebCrypto <-> Python):
//
//	key:        ECDH P-256 of the Edge; public = uncompressed point (65 bytes), base64url without padding
//	key_id:     first 16 hex of SHA-256(point)       fingerprint: first 32 hex, 8 groups of 4 joined by "-"
//	sealing:    ephemeral P-256 -> ECDH -> HKDF-SHA256(salt empty, info "fibercore-seal-v1|"+key_id) -> AES-256-GCM, 12-byte random nonce, AAD below
//	blob:       0x01 || ephemeral_pub(65) || nonce(12) || ciphertext||tag      (base64url, at most 2048 bytes)
//	AAD:        "fibercore-seal-v1\n{tenant}\n{edge}\n{olt_name}\n{kind}\n{delivery_id}\n{key_id}\n{expires_at_unix}"
//	signature:  Ed25519 over "fibercore-delivery-v1\n"+AAD+"\n"+lower-hex(SHA-256(blob bytes)), base64url without padding
//
// No function here ever puts plaintext or key material in an error or a log line.
package oltsecrets

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"golang.org/x/crypto/hkdf"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
)

const (
	blobVersion  = 0x01
	pointLen     = 65
	nonceLen     = 12
	tagLen       = 16
	MaxBlobBytes = 2048
	sealInfoPfx  = "fibercore-seal-v1|"
	aadPrefix    = "fibercore-seal-v1"
	sigPrefix    = "fibercore-delivery-v1"
)

var (
	ErrDecrypt = errors.New("could not open the sealed blob")
	ErrKeyFile = errors.New("seal key file is not usable")
)

// b64 is base64url without padding, strict (a non-canonical encoding is refused).
var b64 = base64.RawURLEncoding.Strict()

// Key is the Edge's sealing key pair. The private half never leaves this struct (no accessor, no String, no JSON).
type Key struct {
	priv *ecdh.PrivateKey
	pub  []byte
}

// KeyID of an uncompressed public point: the first 16 hex of its SHA-256.
func KeyID(point []byte) string {
	h := sha256.Sum256(point)
	return hex.EncodeToString(h[:])[:16]
}

// Fingerprint is what humans compare: the first 32 hex of the SHA-256 of the point, in 8 groups of 4.
func Fingerprint(point []byte) string {
	h := sha256.Sum256(point)
	x := hex.EncodeToString(h[:])[:32]
	parts := make([]string, 0, 8)
	for i := 0; i < 32; i += 4 {
		parts = append(parts, x[i:i+4])
	}
	return strings.Join(parts, "-")
}

func (k *Key) PublicPoint() []byte { return append([]byte(nil), k.pub...) }
func (k *Key) PublicB64() string   { return b64.EncodeToString(k.pub) }
func (k *Key) KeyID() string       { return KeyID(k.pub) }
func (k *Key) Fingerprint() string { return Fingerprint(k.pub) }

// KeyFromScalar builds a key from a 32-byte private scalar (tests and the key file).
func KeyFromScalar(scalar []byte) (*Key, error) {
	priv, err := ecdh.P256().NewPrivateKey(scalar)
	if err != nil {
		return nil, ErrKeyFile
	}
	return &Key{priv: priv, pub: priv.PublicKey().Bytes()}, nil
}

type keyFile struct {
	V       int    `json:"v"`
	Alg     string `json:"alg"`
	Private string `json:"private"` // base64url of the 32-byte scalar
}

// LoadKey reads the key file (mode 0600, directory 0700, ours, a regular file). It never creates anything.
func LoadKey(path string) (*Key, error) {
	if !filepath.IsAbs(path) {
		return nil, fmt.Errorf("%s: %w", path, ErrKeyFile)
	}
	if err := checkPrivateDir(filepath.Dir(path)); err != nil {
		return nil, err
	}
	li, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !li.Mode().IsRegular() {
		return nil, fmt.Errorf("%s (not a regular file): %w", path, ErrKeyFile)
	}
	if li.Mode().Perm()&0o077 != 0 {
		return nil, fmt.Errorf("%s (must be mode 0600): %w", path, ErrKeyFile)
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !fi.Mode().IsRegular() || fi.Mode().Perm()&0o077 != 0 || !credfile.OwnedByUs(fi) || fi.Size() > 4096 {
		return nil, fmt.Errorf("%s: %w", path, ErrKeyFile)
	}
	raw, err := io.ReadAll(io.LimitReader(f, 4097))
	if err != nil {
		return nil, err
	}
	defer credfile.Zero(raw)
	var kf keyFile
	if json.Unmarshal(raw, &kf) != nil || kf.V != 1 || kf.Alg != "ECDH-P256" { // never the decoder's text
		return nil, fmt.Errorf("%s: %w", path, ErrKeyFile)
	}
	scalar, err := b64.DecodeString(kf.Private)
	if err != nil || len(scalar) != 32 {
		return nil, fmt.Errorf("%s: %w", path, ErrKeyFile)
	}
	defer credfile.Zero(scalar)
	k, err := KeyFromScalar(scalar)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, ErrKeyFile)
	}
	return k, nil
}

// LoadOrCreateKey loads the key, or generates it when the file does not exist (first start). The directory is created 0700 when absent. An existing file that cannot be
// read is an ERROR, never a reason to generate a new key: a silent new key would orphan every delivery sealed to the old one.
func LoadOrCreateKey(path string) (k *Key, created bool, err error) {
	k, err = LoadKey(path)
	if err == nil {
		return k, false, nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return nil, false, err
	}
	if !filepath.IsAbs(path) {
		return nil, false, fmt.Errorf("%s: %w", path, ErrKeyFile)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, false, err
	}
	if err := checkPrivateDir(filepath.Dir(path)); err != nil {
		return nil, false, err
	}
	priv, err := ecdh.P256().GenerateKey(rand.Reader)
	if err != nil {
		return nil, false, err
	}
	scalar := priv.Bytes()
	defer credfile.Zero(scalar)
	b, _ := json.Marshal(keyFile{V: 1, Alg: "ECDH-P256", Private: b64.EncodeToString(scalar)})
	defer credfile.Zero(b)
	// installed WITHOUT replacing: a complete temporary file is hard-linked to the final name (link fails if the name exists), so two processes racing here cannot
	// overwrite each other's key and nobody ever sees a partial one. The loser loads the winner's key from disk.
	err = credfile.CreateExclusive(path, b)
	if errors.Is(err, os.ErrExist) {
		k, err = LoadKey(path)
		return k, false, err
	}
	if err != nil {
		return nil, false, err
	}
	k, err = LoadKey(path) // what is on disk is what will be used (and published)
	if err != nil {
		return nil, false, err
	}
	return k, true, nil
}

// AAD builds the associated data of a delivery from the identity of THIS Edge and the delivery's own fields.
func AAD(tenantID, edgeID, oltName, kind, deliveryID, keyID string, expiresUnix int64) []byte {
	return []byte(strings.Join([]string{aadPrefix, tenantID, edgeID, oltName, kind, deliveryID, keyID, strconv.FormatInt(expiresUnix, 10)}, "\n"))
}

// SignedMessage is what the Cloud signs: the AAD bound to the exact blob bytes.
func SignedMessage(aad, blob []byte) []byte {
	h := sha256.Sum256(blob)
	return []byte(sigPrefix + "\n" + string(aad) + "\n" + hex.EncodeToString(h[:]))
}

func deriveAEAD(shared []byte, keyID string) (cipher.AEAD, error) {
	aesKey := make([]byte, 32)
	defer credfile.Zero(aesKey)
	if _, err := io.ReadFull(hkdf.New(sha256.New, shared, nil, []byte(sealInfoPfx+keyID)), aesKey); err != nil {
		return nil, err
	}
	blk, err := aes.NewCipher(aesKey)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(blk)
}

// Open decrypts a blob sealed to this key, checking the AAD. Any failure (format, curve point, tag, AAD) is the same fixed ErrDecrypt.
func (k *Key) Open(blob, aad []byte) ([]byte, error) {
	if len(blob) < 1+pointLen+nonceLen+tagLen || len(blob) > MaxBlobBytes || blob[0] != blobVersion {
		return nil, ErrDecrypt
	}
	eph, err := ecdh.P256().NewPublicKey(blob[1 : 1+pointLen]) // also rejects a point that is not on the curve
	if err != nil {
		return nil, ErrDecrypt
	}
	shared, err := k.priv.ECDH(eph)
	if err != nil {
		return nil, ErrDecrypt
	}
	defer credfile.Zero(shared)
	gcm, err := deriveAEAD(shared, k.KeyID())
	if err != nil {
		return nil, ErrDecrypt
	}
	nonce := blob[1+pointLen : 1+pointLen+nonceLen]
	pt, err := gcm.Open(nil, nonce, blob[1+pointLen+nonceLen:], aad)
	if err != nil {
		return nil, ErrDecrypt
	}
	return pt, nil
}

// SealWith seals plaintext to an Edge public point with a given ephemeral key and nonce (deterministic: this is how the shared test vectors are reproduced).
func SealWith(edgePoint []byte, eph *ecdh.PrivateKey, nonce, aad, plaintext []byte) ([]byte, error) {
	if len(nonce) != nonceLen {
		return nil, errors.New("seal: nonce must be 12 bytes")
	}
	pub, err := ecdh.P256().NewPublicKey(edgePoint)
	if err != nil {
		return nil, errors.New("seal: bad edge public key")
	}
	shared, err := eph.ECDH(pub)
	if err != nil {
		return nil, errors.New("seal: ecdh failed")
	}
	defer credfile.Zero(shared)
	gcm, err := deriveAEAD(shared, KeyID(edgePoint))
	if err != nil {
		return nil, err
	}
	out := make([]byte, 0, 1+pointLen+nonceLen+len(plaintext)+tagLen)
	out = append(out, blobVersion)
	out = append(out, eph.PublicKey().Bytes()...)
	out = append(out, nonce...)
	return gcm.Seal(out, nonce, plaintext, aad), nil
}

// Seal is SealWith with a fresh ephemeral key and a random nonce (what the browser does; used by tests of this repo, never by the Edge itself).
func Seal(edgePoint, aad, plaintext []byte) ([]byte, error) {
	eph, err := ecdh.P256().GenerateKey(rand.Reader)
	if err != nil {
		return nil, err
	}
	nonce := make([]byte, nonceLen)
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}
	return SealWith(edgePoint, eph, nonce, aad, plaintext)
}
