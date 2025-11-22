#!/usr/bin/python
import argparse
import math


#todo write out old sectors as coherent as possible


class XSR1dBlockInfo:
    """ Every first page (0x840 = 4 sector + 4 spare data) of a block contains special block info
        Byte 17-20: block_version
        Byte 21-24: block_number
    """
    @staticmethod
    def parse(first_page, block_start):
        block_version = int.from_bytes(first_page[16:20], 'little')
        block_number = int.from_bytes(first_page[20:24], 'little')

        return XSR1dBlockInfo(block_number, block_version, block_start)

    def __init__(self, block_number, block_version, block_start):
        self.block_number = block_number
        self.block_version = block_version
        self.block_start = block_start

    def __str__(self):
        return f'block_number: {self.block_number}, block_version: {self.block_version}'

class XSR1dSectorInfo:
    """ 4 * 512 bytes sectors followed by 4 * 16 bytes spare data.
        Byte 3 - 6 contains the logical sector number (LSN).
    """
    SECTOR_SIZE = 512
    SECTOR_SPARE_SIZE = 16
    @staticmethod
    def parse_page(spare_bytes, block_info, page_start):
        sector_infos = []
        for i in range(0, 4):
            sector_start = page_start + i * XSR1dSectorInfo.SECTOR_SIZE
            sector_oob_start = 0 + i * XSR1dSectorInfo.SECTOR_SPARE_SIZE
            sector_oob_end = sector_oob_start + XSR1dSectorInfo.SECTOR_SPARE_SIZE
            info = XSR1dSectorInfo._parse_single(spare_bytes[sector_oob_start: sector_oob_end], block_info, sector_start)
            if info is not None:
                sector_infos.append(info)
        return sector_infos

    @staticmethod
    def _parse_single(sector_oob, block_info, sector_start):
        lsn_bytes = sector_oob[2: 5]
        if lsn_bytes == b'\xFF\xFF\xFF':
            # Uninitialized sector, ignore
            return None
        if sector_start == block_info.block_start:
            # first sector of every block is special and doesn't belong to the filesystem
            return None
        lsn = int.from_bytes(lsn_bytes, 'little')
        return XSR1dSectorInfo(lsn, block_info, sector_start)

    def __init__(self, lsn: int, block_info: XSR1dBlockInfo, sector_start: int):
        self.lsn = lsn
        self.block_info = block_info
        self.sector_start = sector_start

    def __str__(self):
        return f'start: {self.sector_start}, lsn: {self.lsn}, block_info: {self.block_info}'


class XSR1d:
    """
        1. build a list of LSN
        2. keep every page offset with this LSN
        3. keep the block number and block version for this LSN
    """
    SECTOR_SIZE = 0x200
    PAGE_SIZE = 0x800
    OOB_SIZE = 0x40
    BLOCK_SIZE = 64

    @staticmethod
    def reconstruct(data):
        reconstructor = XSR1d()
        return reconstructor._reconstruct(data)

    @staticmethod
    def find_start(data):
        """Should start with XSR1d hex: 58 53 52 31 64
        """
        return data.find(b'XSR1d')

    def __init__(self):
        pass

    def _reconstruct(self, data):
        sectors = self.read_metadata(data)
        sector_map = self.build_sector_map(sectors)

        return self.rearrange_data(data, sector_map)

    def read_metadata(self, data):
        block_start = self.find_start(data)
        block_size = self.BLOCK_SIZE * (self.PAGE_SIZE + self.OOB_SIZE)
        n_blocks = math.floor((len(data) - block_start) / block_size)
        print(f'XSR1d starts at {block_start}, size: {len(data)}, n_blocks: {n_blocks}')

        sectors = []
        for i in range(0, n_blocks):
            sectors.extend(self.parse_next_block(data, block_start))
            block_start += block_size

        return sectors

    def parse_next_block(self, data, block_start):
        sectors = []
        page_start = block_start
        page_end = page_start + self.PAGE_SIZE

        block_info = XSR1dBlockInfo.parse(data[page_start: page_end], block_start)
        for i in range(0, self.BLOCK_SIZE):
            sectors.extend(XSR1dSectorInfo.parse_page(data[page_end: page_end + self.OOB_SIZE], block_info, page_start))
            page_start = page_end + self.OOB_SIZE
            page_end = page_start + self.PAGE_SIZE

        return sectors

    @staticmethod
    def build_sector_map(sectors):
        """ every sector has a number, the LSN. rules:
                1. Sectors should be remapped by increasing LSN
                2. If a LSN appears multiple times, take the one belonging to the highest block version, and the
                 highest address with a block
                3. If a LSN doesn't appear, add 512 empty bytes to fill up.
        """
        sector_map = []
        for sector_info in sectors:
            if sector_info.lsn >= len(sector_map):
                n_add = sector_info.lsn - len(sector_map) + 1
                sector_map.extend([None] * n_add)

            if sector_map[sector_info.lsn] is None:
                sector_map[sector_info.lsn] = [sector_info]
            else:
                sector_map[sector_info.lsn].append(sector_info)

        return sector_map

    def rearrange_data(self, data: bytes, sector_map: list):
        rearranged_data = bytearray()

        for sector_infos in sector_map:
            if sector_infos is None:
                rearranged_data.extend(bytearray(b'\xFF') * self.SECTOR_SIZE)
            else:
                sorted_sector_infos = sorted(sector_infos, key=lambda x:(x.block_info.block_version, x.sector_start))
                start = sorted_sector_infos[0].sector_start
                end = start + self.SECTOR_SIZE
                if end > len(data):
                    print(f'Error: trying to add more data then possible.')
                    print(f'start:{start}, end:{end}, sector_info:{sorted_sector_infos[0]}')
                rearranged_data.extend(data[start:end])

        return rearranged_data


def main():
    parser = argparse.ArgumentParser(description="XSR1d Recontruct")
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()

    data = None
    with open(args.input, 'rb') as infile:
        data = infile.read()

    reconstructed_data = XSR1d.reconstruct(data)

    with open(args.output, 'wb') as outfile:
        outfile.write(reconstructed_data)


if __name__=='__main__':
    main()