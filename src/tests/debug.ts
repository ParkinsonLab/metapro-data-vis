import { get_delta } from '../main/data_functions'

const data_1 = [
  {
    'EC#': '0.0.0.0',
    GeneID: 'g1',
    Length: '100',
    Reads: '10',
    RPKM: '1',
    Bacteria: 1000,
    Virus: 1000,
  },
  {
    'EC#': '1.1.1.1',
    GeneID: 'g2',
    Length: '100',
    Reads: '10',
    RPKM: '1',
    Bacteria: 1000,
    Virus: 1000,
  },
]
const data_2 = [
  {
    'EC#': '0.0.0.0',
    GeneID: 'g1',
    Length: '100',
    Reads: '10',
    RPKM: '1',
    Bacteria: 2000,
    Archea: 500,
  },
  {
    'EC#': '1.1.1.1',
    GeneID: 'g2',
    Length: '100',
    Reads: '10',
    RPKM: '1',
    Bacteria: 2000,
    Archea: 500,
  },
]

get_delta(data_1, data_2)