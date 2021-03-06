"""

    THIS CODE WAS FOR DEMO AND BUILD PURPOSES, IT HAS A NUMBER OF ERRORS, 
    I HAVE INCLUDED IT HERE TO HELP YOU UNDERSTAND HOW EVERYTHING WORKS


    IF SOME PARTS WON'T MAKE SENSE, YOU SHOULD READ MORE ON IT.

    USE THE my_cl_dsse.py FILE TO TEST SECTION FIVE RESULTS WITH THE TEST FILES

"""

import argparse
import array
import base64
import hashlib
import logging
import logging.handlers
import math
import os
import pickle
import queue
import random
import re
import signal
import socket
import ssl
import string
import sys
import threading
import time

from Crypto.Cipher import AES


class DSSEClient:

    # Enumerate the total size of the plaintexts (paper uses |c| / 8 to guide array size)
    def totalsize(self, files):
        sum = 0
        for file in files:
            try:
                sum += os.path.getsize(file)
            except os.error:
                print("Unable to get size of {0}.").format(file)
        return sum

    # This is the tokenizer. Replace this function whenever the input isn't text-based.
    def fbar(self, filename):
        fbar = []
        # Match anything that isn't alphanumeric or space so only words separated by spaces are left
        stripper = re.compile(r"([^\s\w])+")
        with open(filename, "r") as f:
            for line in f:
                line = stripper.sub("", line)
                words = line.split()
                for word in words:
                    if word not in fbar:
                        fbar.append(word)
        return fbar

    """
    The following functions up to and including filehashes() perform all the keyed hashing
    on keywords and files, respectively. F, G and P are HMAC-SHA256 hashes, id is SHA1 and
    H(1,2) are SHA512. Since G needs to be variable length to cover the dictionary entries
    we feed the key and data into it repeatedly if needed to get the required output, ess-
    entially using the algorithm as a stream cipher.
    """

    def F(self, data):
        return hashlib.sha256(self.K1 + data).digest()

    def G(self, data):
        hash = hashlib.sha256(self.K2 + data)
        G = hash.digest()
        while 2 * self.addr_size > len(G):
            G += hash.update(self.K2).digest()
        return G[: 2 * self.addr_size]

    def P(self, data):
        return hashlib.sha256(self.K3 + data).digest()

    def Hx(self, data, length):
        hash = hashlib.sha512(data)
        Hx = hash.digest()
        while length > len(Hx):
            hash.update(data)
            Hx += hash.digest()
        return Hx[:length]

    def H1(self, data):
        return self.Hx(data, self.id_size + self.addr_size)

    def H2(self, data):
        return self.Hx(data, 6 * self.addr_size + self.k)

    def filehashes(self, filename):
        id = hashlib.sha1(filename)  # Only used to identify file, no cryptographic use
        Ff = hashlib.sha256(self.K1)
        Gf = hashlib.sha256(self.K2)
        Pf = hashlib.sha256(self.K3)
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(128 * id.block_size), b""):
                Ff.update(chunk)
                Gf.update(chunk)
                Pf.update(chunk)
        Gfstring = Gf.digest()
        while self.addr_size > len(Gfstring):
            Gfstring += Gf.update(self.K2).digest()
        return (Ff.digest(), Gfstring[: self.addr_size], Pf.digest(), id.digest())

    # FIXME: after demo time we should figure out why addresses appear to all be in a
    # very compressed range. Most likely either this or the commented out version below
    # works fine and the problem is elsewhere.
    def findusable(self, array):
        while True:
            rndbytes = int(math.ceil(math.log(len(array), 256)))
            addr = (int(os.urandom(rndbytes).encode("hex"), 16) % (len(array) - 2)) + 1
            if array[addr] is None:
                return addr

    """
    def findusable(self, array):
        while True:
            addr = random.randrange(1, len(array))
            if array[addr] is None:
                break
        return addr
    """

    # File encryption is done with AES because it is the best-known and most-vetted
    # symmetric key algorithm available today. We employ PyCrypto to do the heavy lifting.
    def SKEEnc(self, filename):
        iv = os.urandom(16)
        cipher = AES.new(self.K4, AES.MODE_CFB, iv)
        with open(filename, "rb") as src:
            with open(filename + ".enc", "wb") as dst:
                dst.write(iv)
                for chunk in iter(lambda: src.read(AES.block_size * 128), b""):
                    if len(chunk) != AES.block_size * 128:
                        break
                    dst.write(cipher.encrypt(chunk))
                # Perform PKCS7 padding
                if len(chunk) == AES.block_size * 128:
                    dst.write(cipher.encrypt(chr(16) * 16))
                else:
                    remainder = len(chunk) % 16
                    if remainder == 0:
                        remainder = 16
                    chunk += chr(remainder) * remainder
                    dst.write(cipher.encrypt(chunk))

    # Adaptation of SKEDec to apply AES decryption to the file specified in 'filename'
    def SKEDec(self, filename):
        with open(filename, "rb") as src:
            with open(string.strip(filename, ".enc") + ".dec", "wb+") as dst:
                iv = src.read(16)
                cipher = AES.new(self.K4, AES.MODE_CFB, iv)
                for chunk in iter(lambda: src.read(AES.block_size * 128), b""):
                    dst.write(cipher.decrypt(chunk))

                # Remove PKCS7 padding. No check is performed to see whether padding was
                # correct, which is a possible TODO for publication.
                dst.seek(-1, os.SEEK_END)
                lastbyte = dst.read(1)
                dst.seek(-int(lastbyte.encode("hex"), 16), os.SEEK_END)
                dst.truncate()

    # Python only has built-in support to XOR numbers, so take a string, interpret it as
    # a series of unsigned chars, XOR those and stitch back together.
    # Could probably be done more efficiently, which is a TODO for publication.
    def xor(self, str1, str2):
        # TODO: this is for testing purposes and should be removed for publication
        if len(str1) != len(str2):
            print("Strings of unequal length: {} and {}").format(len(str1), len(str2))
            test = 0 / 0
            return None
        a1 = array.array("B", str1)
        a2 = array.array("B", str2)
        ret = array.array("B")
        for idx in range(len(a1)):
            ret.append(a1[idx] ^ a2[idx])
        return ret.tostring()

    def pad(self, addr):
        return str(addr).zfill(self.addr_size)

    def split(self, entry, splitPt):
        lhs = entry[:splitPt]
        rhs = entry[splitPt:]
        return lhs, rhs

    def __init__(self, k=32, z=100000):
        self.K1 = 0
        self.K2 = 0
        self.K3 = 0
        self.K4 = 0
        self.k = k
        self.z = z
        self.id_size = 20  # SHA1 is used for file ID and is 20 bytes long. Currently not changeable
        self.addr_size = 0

    def importkeys(self, keys):
        self.K1 = keys[0]
        self.K2 = keys[1]
        self.K3 = keys[2]
        self.K4 = keys[3]
        self.k = len(self.K1)

    # Only export keys /after/ Enc, since addr_size is unknown otherwise
    def exportkeys(self):
        return (self.K1, self.K2, self.K3, self.K4)

    def set_address_size(self, addr_size):
        self.addr_size = addr_size

    def Gen(self):
        self.K1 = os.urandom(self.k)
        self.K2 = os.urandom(self.k)
        self.K3 = os.urandom(self.k)
        self.K4 = os.urandom(self.k)
        self.keys = (self.K1, self.K2, self.K3, self.K4)
        return self.keys

    # The biggest function here, with the least granular breakdown of steps. Inline comments
    # provided where needed.
    def Enc(self, files):  # sourcery no-metrics
        bytes = self.totalsize(files)
        iddb = {}

        # Step 1
        As = [None] * (bytes + self.z)
        Ad = [None] * (bytes + self.z)
        addr_size = int(math.ceil(math.log(len(As), 10)))
        self.addr_size = addr_size
        zerostring = "\0" * self.addr_size
        Ts = {}
        Td = {}

        # Steps 2 and 3, interleaved
        for filename in files:
            (Ff, Gf, Pf, id) = self.filehashes(
                filename.encode("utf-8")
            )  # , self.K1, self.K2, self.K3, self.K4) #TODO -> HERE
            iddb[id] = filename

            addr_d_D1 = zerostring  # Temporary Td pointer to build Di chain. Will be updated in each word iteration below to point to the previous dual node

            for w in self.fbar(filename):
                addr_As = self.pad(self.findusable(As))  # insert new node here
                addr_Ad = self.pad(self.findusable(Ad))  # insert dual node here
                Fw = self.F(w)
                Gw = self.G(w)
                Pw = self.P(w)
                r = os.urandom(self.k)
                H1 = self.H1(Pw + r)

                # Get pointers to first (dual) node in search list, which is zero for new words.
                if Fw in Ts:
                    Ts_entry = Ts[Fw]
                    Ts_entry = self.xor(Ts_entry, Gw)
                    addr_s_N1, addr_d_N1 = self.split(Ts_entry, self.addr_size)
                else:
                    addr_s_N1 = zerostring
                    addr_d_N1 = zerostring

                Ts_entry = self.xor(addr_As + addr_Ad, Gw)
                Ts[Fw] = Ts_entry

                searchnode = self.xor(id + self.pad(addr_s_N1), H1) + r
                As[int(addr_As)] = searchnode

                deletenode = (
                    addr_d_D1
                    + zerostring
                    + addr_d_N1
                    + addr_As
                    + zerostring
                    + addr_s_N1
                    + Fw
                )
                rp = os.urandom(self.k)
                deletenode = self.xor(deletenode, self.H2(Pf + rp)) + rp
                Ad[int(addr_Ad)] = deletenode

                # We get the dual of N+1. From its perspective we are N-1. Then we update
                # its values to point to us. This is the crucial interleaving step.
                if addr_d_N1 != zerostring:
                    prevD = Ad[int(addr_d_N1)]
                    # set prevD's second field to addr_Ad and fifth field to addr_As
                    xorstring = (
                        zerostring
                        + addr_Ad
                        + 2 * zerostring
                        + addr_As
                        + zerostring
                        + len(self.K1) * 2 * "\0"
                    )
                    prevD = self.xor(prevD, xorstring)
                    Ad[int(addr_d_N1)] = prevD

                addr_d_D1 = addr_Ad  # update the temporary Td pointer

            Td[Ff] = self.xor(addr_d_D1, Gf)

        # Step 4
        prev_free = zerostring
        for _ in range(self.z):
            free = self.findusable(As)
            free_dual = self.findusable(Ad)
            As[free] = self.pad(prev_free) + self.pad(free_dual)
            prev_free = free
            # the algo doesn't mention processing the free nodes in any way, even though
            # Del() on the server does. Here we set them to zerostring to distinguish from
            # None in step 5. Consistency is a TODO for publication.
            Ad[free_dual] = zerostring
        Ts["free"] = self.pad(prev_free) + zerostring

        # Step 5
        for idx in range(len(As)):
            if As[idx] is None:
                As[idx] = os.urandom(2 * addr_size)
            if Ad[idx] is None:
                Ad[idx] = os.urandom(6 * addr_size + 2 * self.k)

        # Step 6
        for filename in files:
            self.SKEEnc(filename)

        # Step 7, instead of returning the databases to caller we write out to disk.
        # Caller can now transport them to the server as files and have the server unpicle
        # them. No integrity checks are performed, so if needed the caller should provide
        # additional checking mechanisms.
        with open("as.db", "wb") as Asdb:
            pickle.dump(As, Asdb)

        with open("ts.db", "wb") as Tsdb:
            pickle.dump(Ts, Tsdb)

        with open("ad.db", "wb") as Addb:
            pickle.dump(Ad, Addb)

        with open("td.db", "wb") as Tddb:
            pickle.dump(Td, Tddb)

        with open("id.db", "wb") as IDdb:
            pickle.dump(iddb, IDdb)

    def SrchToken(self, w):
        return (self.F(w), self.G(w), self.P(w))

    # The function should return the token and cf, but we have cf on disk. Caller can
    # decide how to transfer the ciphertext to the server.
    # For each word a search and deletenode need to be generated. The server will update
    # these with appropriate addresses homomorphically.
    def AddToken(self, filename):
        # Get ALL the hashes!
        (Ff, Gf, Pf, id) = self.filehashes(filename)
        lamda = []
        zerostring = "\0" * self.addr_size
        for w in self.fbar(filename):
            r = os.urandom(self.k)
            rp = os.urandom(self.k)
            Fw = self.F(w)
            Gw = self.G(w)
            Pw = self.P(w)
            H1 = self.H1(Pw + r)
            H2 = self.H2(Pf + rp)
            lamda_i = (
                Fw
                + Gw
                + self.xor(id + zerostring, H1)
                + r
                + self.xor(6 * zerostring + Fw, H2)
                + rp
            )
            lamda.append(lamda_i)
        self.SKEEnc(filename)
        return (Ff, Gf, lamda)

    def DelToken(self, filename):
        return self.filehashes(filename)

    def Dec(self, filename):
        self.SKEDec(filename)
