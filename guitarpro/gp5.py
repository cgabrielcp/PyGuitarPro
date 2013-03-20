# This file is part of alphaTab.
#
#  alphaTab is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  alphaTab is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with alphaTab.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import division

import math
import copy

import base as gp
import gp4

# TODO: There must be a wah wah flag somewhere. 
class GP5File(gp4.GP4File):
    '''A reader for GuitarPro 5 files. 
    '''
    def __init__(self, *args, **kwargs):
        super(GP5File, self).__init__(*args, **kwargs)
        self.initVersions(['FICHIER GUITAR PRO v5.00', 'FICHIER GUITAR PRO v5.10'])
    
    #################################################################
    #### Reading
    #################################################################

    def readSong(self) :
        if not self.readVersion():
            raise gp.GuitarProException("unsupported version '%s'" % self.version)

        song = gp.Song()
        self.readInfo(song)
        
        self.readLyrics(song)
        
        self.readPageSetup(song)
        song.tempoName = self.readIntSizeCheckByteString()
        song.tempo = self.readInt()
                
        if not self.version.endswith('5.00'):
            song.hideTempo = self.readBool()
        
        song.key = self.readByte()
        song.octave = self.readInt()
        
        channels = self.readMidiChannels()
        
        self.skip(42) # RSE info?
        measureCount = self.readInt()
        trackCount = self.readInt()
        
        self.readMeasureHeaders(song, measureCount)
        self.readTracks(song, trackCount, channels)
        self.readMeasures(song)
        
        return song
        
    def readMeasure(self, measure, track):
        for voice in range(gp.Beat.MAX_VOICES):
            start = measure.start()
            beats = self.readInt()
            for beat in range(beats):
                start += self.readBeat(start, measure, track, voice)
        self.skip(1)
    
    def readBeat(self, start, measure, track, voiceIndex):
        flags = self.readByte()
        
        beat = self.getBeat(measure, start)
        voice = beat.voices[voiceIndex]
        
        if flags & 0x40 != 0:
            beatType = self.readByte()
            voice.isEmpty = (beatType & 0x02) == 0
        
        duration = self.readDuration(flags)
        if flags & 0x02 != 0:
            self.readChord(track.stringCount(), beat)

        if flags & 0x04 != 0:
            self.readText(beat)

        if flags & 0x08 != 0:
            self.readBeatEffects(beat, None)

        if flags & 0x10 != 0:
            mixTableChange = self.readMixTableChange(measure)
            beat.effect.mixTableChange = mixTableChange

        stringFlags = self.readByte()
        for j in range(7):
            i = 6 - j
            if stringFlags & (1 << i) != 0 and (6 - i) < track.stringCount():
                # guitarString = track.strings[6 - i].clone(factory)
                guitarString = copy.copy(track.strings[6 - i])
                note = self.readNote(guitarString, track, gp.NoteEffect())
                voice.addNote(note)
            # duration.copy(voice.duration)
            voice.duration = copy.copy(duration)
        
        self.skip(1)
        
        read = self.readByte()
        if read == 8 or read == 10:
            self.skip(1)

        return duration.time() if not voice.isEmpty else 0
    
    def readNote(self, guitarString, track, effect):
        flags = self.readByte()
        note = gp.Note()
        note.string = guitarString.number
        note.effect.accentuatedNote = (flags & 0x40) != 0
        note.effect.heavyAccentuatedNote = (flags & 0x02) != 0
        note.effect.ghostNote = (flags & 0x04) != 0
        if flags & 0x20 != 0:
            noteType = self.readByte()
            note.isTiedNote = noteType == 0x02
            note.effect.deadNote = noteType == 0x03
        
        if flags & 0x10 != 0:
            dyn = self.readSignedByte()
            note.velocity = self.unpackVelocity(dyn)
        
        if flags & 0x20 != 0:
            fret = self.readSignedByte()
            value = self.getTiedNoteValue(guitarString.number, track) if note.isTiedNote else fret
            note.value = value if 0 <= value < 100 else 0
        
        if flags & 0x80 != 0:
            note.effect.leftHandFinger = self.readSignedByte()
            note.effect.rightHandFinger = self.readSignedByte()
            note.effect.isFingering = True

        if flags & 0x01 != 0:
            note.durationPercent = self.readDouble()
        flags2 = self.readByte()
        note.swapAccidentals = (flags2 & 0x02) != 0
        
        if flags & 0x08 != 0:
            self.readNoteEffects(note.effect)
            # as with BeatEffects, some effects like 'slide into' are not supported in GP3, 
            # but effect flag is still 1
            note.effect.presence = True
        
        return note

    def readNoteEffects(self, noteEffect):
        flags1 = self.readByte()
        flags2 = self.readByte()
        if flags1 & 0x01 != 0:
            self.readBend(noteEffect)
        if flags1 & 0x10 != 0:
            self.readGrace(noteEffect)
        if flags2 & 0x04 != 0:
            self.readTremoloPicking(noteEffect)
        if flags2 & 0x08 != 0:
            noteEffect.slide = self.fromSlideType(self.readByte())
        if flags2 & 0x10 != 0:
            self.readArtificialHarmonic(noteEffect)
        if flags2 & 0x20 != 0:
            self.readTrill(noteEffect)
        noteEffect.letRing = (flags1 & 0x08) != 0
        noteEffect.hammer = (flags1 & 0x02) != 0
        noteEffect.vibrato = (flags2 & 0x40) != 0 or noteEffect.vibrato
        noteEffect.palmMute = (flags2 & 0x02) != 0
        noteEffect.staccato = (flags2 & 0x01) != 0    
    
    def fromHarmonicType(self, harmonicType):
        if harmonicType == 1:
            return (0, gp.HarmonicType.Natural)
        elif harmonicType == 2:
            self.skip(3) # Note?
            return (0, gp.HarmonicType.Artificial)
        elif harmonicType == 3:
            self.skip(1) # Key?
            return (0, gp.HarmonicType.Tapped)
        elif harmonicType == 4:
            return (0, gp.HarmonicType.Pinch)
        elif harmonicType == 5:
            return (0, gp.HarmonicType.Semi)

    def readGrace(self, noteEffect):
        fret = self.readByte()
        dyn = self.readByte()
        transition = self.readByte()
        duration = self.readByte()
        flags = self.readByte()
        grace = gp.GraceEffect()
        
        grace.fret = fret
        grace.velocity = self.unpackVelocity(dyn)
        grace.duration = duration
        grace.isDead = (flags & 0x01) != 0
        grace.isOnBeat = (flags & 0x02) != 0
        grace.transition = self.toGraceTransition(transition)
        
        noteEffect.grace = grace
    
    def readMixTableChange(self, measure):
        tableChange = gp.MixTableChange()
        tableChange.instrument.value = self.readSignedByte()
        self.skip(16) # RSE info
        tableChange.volume.value = self.readSignedByte()
        tableChange.balance.value = self.readSignedByte()
        tableChange.chorus.value = self.readSignedByte()
        tableChange.reverb.value = self.readSignedByte()
        tableChange.phaser.value = self.readSignedByte()
        tableChange.tremolo.value = self.readSignedByte()
        tableChange.tempoName = self.readIntSizeCheckByteString()
        tableChange.tempo.value = self.readInt()
        
        if tableChange.instrument.value < 0:
            tableChange.instrument = None
        
        if tableChange.volume.value >= 0:
            tableChange.volume.duration = self.readSignedByte()
        else:
            tableChange.volume = None
        if tableChange.balance.value >= 0:
            tableChange.balance.duration = self.readSignedByte()
        else:
            tableChange.balance = None
        if tableChange.chorus.value >= 0:
            tableChange.chorus.duration = self.readSignedByte()
        else:
            tableChange.chorus = None
        if tableChange.reverb.value >= 0:
            tableChange.reverb.duration = self.readSignedByte()
        else:
            tableChange.reverb = None
        if tableChange.phaser.value >= 0:
            tableChange.phaser.duration = self.readSignedByte()
        else:
            tableChange.phaser = None
        if tableChange.tremolo.value >= 0:
            tableChange.tremolo.duration = self.readSignedByte()
        else:
            tableChange.tremolo = None
        if tableChange.tempo.value >= 0:
            tableChange.tempo.duration = self.readSignedByte()
            measure.tempo().value = tableChange.tempo.value
            tableChange.hideTempo = not self.version.endswith('5.00') and self.readBool()
        else:
            tableChange.tempo = None

        allTracksFlags = self.readByte()
        if tableChange.volume is not None:
            tableChange.volume.allTracks = (allTracksFlags & 0x01) != 0
        if tableChange.balance is not None:
            tableChange.balance.allTracks = (allTracksFlags & 0x02) != 0
        if tableChange.chorus is not None:
            tableChange.chorus.allTracks = (allTracksFlags & 0x04) != 0
        if tableChange.reverb is not None:
            tableChange.reverb.allTracks = (allTracksFlags & 0x08) != 0
        if tableChange.phaser is not None:
            tableChange.phaser.allTracks = (allTracksFlags & 0x10) != 0
        if tableChange.tremolo is not None:
            tableChange.tremolo.allTracks = (allTracksFlags & 0x20) != 0
        if tableChange.tempo is not None:
            tableChange.tempo.allTracks = True

        self.skip(1)
        if not self.version.endswith('5.00'):
            tableChange.skip1 = self.readIntSizeCheckByteString()
            tableChange.skip2 = self.readIntSizeCheckByteString()

        return tableChange
    
    def readChord(self, stringCount, beat):
        chord = gp.Chord(stringCount)
        self.skip(17)
        chord.name = self.readByteSizeString(21)
        self.skip(4)
        chord.firstFret = self.readInt()
        for i in range(7):
            fret = self.readInt()
            if i < len(chord.strings):
                chord.strings[i] = fret
        self.skip(32)
        if chord.noteCount() > 0:
            beat.setChord(chord)
    
    def readTracks(self, song, trackCount, channels) :
        for i in range(trackCount):
            song.addTrack(self.readTrack(i + 1, channels))
        self.skip(2 if self.version.endswith('5.00') else 1)
    
    def readTrack(self, number, channels) :
        flags = self.readByte()
        if number == 1 or self.version.endswith('5.00'):
            self.skip(1)
        track = gp.Track()
        track.isPercussionTrack = (flags & 0x1) != 0
        track.is12StringedGuitarTrack = (flags & 0x02) != 0
        track.isBanjoTrack = (flags & 0x04) != 0
        track.visible = (flags & 0x08) != 0
        track.number = number
        track.name = self.readByteSizeString(40)
        stringCount = self.readInt()
        for i in range(7):
            iTuning = self.readInt()
            if stringCount > i:
                oString = gp.GuitarString()
                oString.number = i + 1
                oString.value = iTuning
                track.strings.append(oString)
        track.port = self.readInt()
        self.readChannel(track, channels)
        if track.channel.channel == 9:
            track.isPercussionTrack = True
        track.fretCount = self.readInt()
        track.offset = self.readInt()
        track.color = self.readColor()
        self.skip(49 if not self.version.endswith('5.00') else 44)
        if not self.version.endswith('5.00'):
            track.skip1 = self.readIntSizeCheckByteString()
            track.skip2 = self.readIntSizeCheckByteString()
        return track

    def unpackTripletFeel(self, tripletFeel):
        if tripletFeel == 1:
            return gp.TripletFeel.Eighth
        elif tripletFeel == 2:
            return gp.TripletFeel.Sixteenth
        else:
            return gp.TripletFeel.None_
    
    def readMeasureHeader(self, i, timeSignature, song):
        if i > 0:
            self.skip(1)
        
        flags = self.readByte()
        
        header = gp.MeasureHeader()
        header.number = i + 1
        header.start = 0
        header.tempo.value = song.tempo
        
        if flags & 0x01 != 0:
            timeSignature.numerator = self.readByte()
        if flags & 0x02 != 0:
            timeSignature.denominator.value = self.readByte()
        
        header.isRepeatOpen = (flags & 0x04) != 0
        
        # timeSignature.copy(header.timeSignature)
        header.timeSignature = copy.deepcopy(timeSignature)
        
        if flags & 0x08 != 0:
            header.repeatClose = self.readByte() - 1
        
        if flags & 0x20 != 0:
            header.marker = self.readMarker(header)
        
        if flags & 0x10 != 0:
            header.repeatAlternative = self.readByte()
        
        if flags & 0x40 != 0:
            header.keySignature = self.toKeySignature(self.readSignedByte())
            header.keySignatureType = self.readByte()
        elif header.number > 1:
            header.keySignature = song.measureHeaders[i - 1].keySignature
            header.keySignatureType = song.measureHeaders[i - 1].keySignatureType

        header.hasDoubleBar = (flags & 0x80) != 0

        if flags & 0x01 != 0:
            self.skip(4)

        if flags & 0x10 == 0:
            self.skip(1)
        
        header.tripletFeel = self.unpackTripletFeel(self.readByte())
        
        return header
    
    def readPageSetup(self, song):
        setup = gp.PageSetup()
        if not self.version.endswith('5.00'):
            self.skip(19)
        setup.pageSize = gp.Point(self.readInt(), self.readInt())
        
        l = self.readInt()
        r = self.readInt()
        t = self.readInt()
        b = self.readInt() 
        setup.pageMargin = gp.Padding(l, t, r, b)
        setup.scoreSizeProportion = self.readInt() / 100.0
        
        setup.headerAndFooter = self.readByte()
        
        flags2 = self.readByte()
        if flags2 & 0x01 != 0:
            setup.headerAndFooter |= gp.HeaderFooterElements.PAGE_NUMBER
        
        setup.title = self.readIntSizeCheckByteString()
        setup.subtitle = self.readIntSizeCheckByteString()
        setup.artist = self.readIntSizeCheckByteString()
        setup.album = self.readIntSizeCheckByteString()
        setup.words = self.readIntSizeCheckByteString()
        setup.music = self.readIntSizeCheckByteString()
        setup.wordsAndMusic = self.readIntSizeCheckByteString()
        setup.copyright = self.readIntSizeCheckByteString() + '\n' + self.readIntSizeCheckByteString()
        setup.pageNumber = self.readIntSizeCheckByteString()
        song.pageSetup = setup
    
    def readInfo(self, song):
        song.title = self.readIntSizeCheckByteString()
        song.subtitle = self.readIntSizeCheckByteString()
        song.artist = self.readIntSizeCheckByteString()
        song.album = self.readIntSizeCheckByteString()
        song.words = self.readIntSizeCheckByteString()
        song.music = self.readIntSizeCheckByteString()
        song.copyright = self.readIntSizeCheckByteString()
        song.tab = self.readIntSizeCheckByteString()
        song.instructions = self.readIntSizeCheckByteString()
        
        iNotes = self.readInt()
        song.notice = []
        for i in range(iNotes):
            song.notice.append(self.readIntSizeCheckByteString())

    #################################################################
    #### Writing
    #################################################################

    def writeSong(self, song) :
        self.version = self._supportedVersions[1]
        self.writeVersion(1)

        self.writeInfo(song)
        self.writeLyrics(song)
        self.writePageSetup(song.pageSetup)

        self.writeIntSizeCheckByteString(song.tempoName)
        self.writeInt(song.tempo)
                
        if not self.version.endswith('5.00'):
            self.writeBool(song.hideTempo)
        
        self.writeByte(song.key)
        self.writeInt(song.octave)
        
        self.writeMidiChannels(song)
        
        self.placeholder(42, '\xff') # RSE info?

        measureCount = len(song.tracks[0].measures)
        trackCount = len(song.tracks)        
        self.writeInt(measureCount)
        self.writeInt(trackCount)
        
        self.writeMeasureHeaders(song)
        self.writeTracks(song.tracks)
        self.writeMeasures(song)

    def writeInfo(self, song):
        self.writeIntSizeCheckByteString(song.title)
        self.writeIntSizeCheckByteString(song.subtitle)
        self.writeIntSizeCheckByteString(song.artist)
        self.writeIntSizeCheckByteString(song.album)
        self.writeIntSizeCheckByteString(song.words)
        self.writeIntSizeCheckByteString(song.music)
        self.writeIntSizeCheckByteString(song.copyright)
        self.writeIntSizeCheckByteString(song.tab)
        self.writeIntSizeCheckByteString(song.instructions)
        
        self.writeInt(len(song.notice))
        for line in song.notice:
            self.writeIntSizeCheckByteString(line)

    def writePageSetup(self, setup):
        if not self.version.endswith('5.00'):
            self.placeholder(19)
        self.writeInt(setup.pageSize.x)
        self.writeInt(setup.pageSize.y)
        
        self.writeInt(setup.pageMargin.left)
        self.writeInt(setup.pageMargin.right)
        self.writeInt(setup.pageMargin.top)
        self.writeInt(setup.pageMargin.bottom)
        self.writeInt(setup.scoreSizeProportion * 100)
        
        self.writeByte(setup.headerAndFooter & 0xff)
        
        flags2 = 0x00
        if setup.headerAndFooter & gp.HeaderFooterElements.PAGE_NUMBER != 0:
            flags2 |= 0x01
        self.writeByte(flags2)
        
        self.writeIntSizeCheckByteString(setup.title)
        self.writeIntSizeCheckByteString(setup.subtitle)
        self.writeIntSizeCheckByteString(setup.artist)
        self.writeIntSizeCheckByteString(setup.album)
        self.writeIntSizeCheckByteString(setup.words)
        self.writeIntSizeCheckByteString(setup.music)
        self.writeIntSizeCheckByteString(setup.wordsAndMusic)
        copyrighta, copyrightb = setup.copyright.split('\n', 1)
        self.writeIntSizeCheckByteString(copyrighta)
        self.writeIntSizeCheckByteString(copyrightb)
        self.writeIntSizeCheckByteString(setup.pageNumber)

    def packTripletFeel(self, tripletFeel):
        if tripletFeel == gp.TripletFeel.None_:
            return 0
        elif tripletFeel == gp.TripletFeel.Eighth:
            return 1
        elif tripletFeel == gp.TripletFeel.Sixteenth:
            return 2

    def writeMeasureHeader(self, song, header, previous):
        flags = 0x00
        if previous is not None:
            if header.timeSignature.numerator != previous.timeSignature.numerator:
                flags |= 0x01
            if header.timeSignature.denominator.value != previous.timeSignature.denominator.value:
                flags |= 0x02
        else:
            flags |= 0x01
            flags |= 0x02
        if header.isRepeatOpen:
            flags |= 0x04
        if header.repeatClose > -1:
            flags |= 0x08
        if header.repeatAlternative != 0:
            flags |= 0x10
        if header.marker is not None:
            flags |= 0x20
        if previous is not None:
            if header.keySignature != previous.keySignature:
                flags |= 0x40
        else:
            flags |= 0x40
        if header.hasDoubleBar:
            flags |= 0x80

        if header.number > 1:
            self.placeholder(1)

        self.writeByte(flags)
                
        if flags & 0x01 != 0:
            self.writeByte(header.timeSignature.numerator)
        if flags & 0x02 != 0:
            self.writeByte(header.timeSignature.denominator.value)
        
        if flags & 0x08 != 0:
            self.writeByte(header.repeatClose + 1)

        if flags & 0x20 != 0:
            self.writeMarker(header.marker)
        
        if flags & 0x10 != 0:
            self.writeByte(header.repeatAlternative)
        
        if flags & 0x40 != 0:
            self.writeSignedByte(self.fromKeySignature(header.keySignature))
            self.writeByte(header.keySignatureType)

        if flags & 0x01 != 0:
            self.placeholder(4)

        if flags & 0x10 == 0:
            self.placeholder(1)
        
        self.writeByte(self.packTripletFeel(header.tripletFeel))

    def writeTracks(self, tracks):
        super(GP5File, self).writeTracks(tracks)
        self.placeholder(2 if self.version.endswith('5.00') else 1)
        
    def writeTrack(self, track):
        flags = 0x00
        if track.isPercussionTrack:
            flags |= 0x01
        if track.is12StringedGuitarTrack:
            flags |= 0x02
        if track.isBanjoTrack:
            flags |= 0x04
        if track.visible:
            flags |= 0x08

        self.writeByte(flags)
        if track.number == 1 or self.version.endswith('5.00'):
            self.writeByte(8 | flags)
            # self.placeholder(1)

        self.writeByteSizeString(track.name, 40)
        self.writeInt(track.stringCount())
        for i in range(7):
            if i < track.stringCount():
                tuning = track.strings[i].value
            else:
                tuning = 0
            self.writeInt(tuning)
        self.writeInt(track.port)
        self.writeChannel(track)
        self.writeInt(track.fretCount)
        self.writeInt(track.offset)
        self.writeColor(track.color)

        if self.version.endswith('5.00'):
            self.data.write('\x43\x01\x00\x00\x00\x00\x00\x00'
                            '\x00\x00\x00\x00\x00\x64\x00\x00'
                            '\x00\x01\x02\x03\x04\x05\x06\x07'
                            '\x08\x09\x0a\xff\x03\xff\xff\xff'
                            '\xff\xff\xff\xff\xff\xff\xff\xff'
                            '\xff\xff\xff\xff')
        else:
            self.data.write('\xc3\x00\x00\x00\x00\x0c\x00\x00'
                            '\x00\x0c\x00\x00\x00\x64\x00\x00'
                            '\x00\x01\x02\x03\x04\x05\x06\x0a'
                            '\x07\x08\x09\xdf\x03\x1e\x00\x00'
                            '\x00\x01\x00\x00\x00\x01\x00\x00'
                            '\x00\x00\x00\x00\x00\x00\x00\x00'
                            '\x00')
        if not self.version.endswith('5.00'):
            self.writeIntSizeCheckByteString(track.skip1)
            self.writeIntSizeCheckByteString(track.skip2)

    def writeMeasure(self, measure, track):
        for voice in range(gp.Beat.MAX_VOICES):
            beatCount = measure.beatCount(voice)
            if beatCount == 0:
                beatCount = 1
            self.writeInt(beatCount)
            # for beat in measure.beats:
            for i in range(beatCount):
                beat = measure.beats[i]
                self.writeBeat(beat, measure, track, voice)
        self.placeholder(1)

    def writeBeat(self, beat, measure, track, voiceIndex=0):
        voice = beat.voices[voiceIndex]

        flags = 0x00
        if voice.duration.isDotted:
            flags |= 0x01
        if beat.effect.isChord():
            flags |= 0x02
        if beat.text is not None:
            flags |= 0x04
        if not beat.effect.isDefault():
            flags |= 0x08
        if beat.effect.mixTableChange is not None:
            flags |= 0x10
        if voice.duration.tuplet != gp.Tuplet():
            flags |= 0x20
        if voice.isEmpty or voice.isRestVoice():
            flags |= 0x40

        self.writeByte(flags)
                
        if flags & 0x40 != 0:
            beatType = 0x00 if voice.isEmpty else 0x02
            self.writeByte(beatType)
        
        self.writeDuration(voice.duration, flags)

        if flags & 0x02 != 0:
            self.writeChord(beat.effect.chord)

        if flags & 0x04 != 0:
            self.writeText(beat.text)

        if flags & 0x08 != 0:
            self.writeBeatEffects(beat.effect, voice)

        if flags & 0x10 != 0:
            self.writeMixTableChange(beat.effect.mixTableChange)

        stringFlags = 0x00
        for note in voice.notes:
            stringFlags |= 1 << (7 - note.string)
        self.writeByte(stringFlags)

        previous = None
        for note in voice.notes:
            self.writeNote(note, previous, track)
            previous = note

        self.placeholder(2)

    def writeNote(self, note, previous, track):
        flags = 0x00
        try:
            if note.duration is not None and note.tuplet is not None:
                flags |= 0x01
        except AttributeError:
            pass
        if note.durationPercent != 1.0:
            flags |= 0x01
        if note.effect.heavyAccentuatedNote:
            flags |= 0x02
        if note.effect.ghostNote:
            flags |= 0x04
        if not note.effect.isDefault() or note.effect.presence:
            flags |= 0x08
        # if previous is not None and note.velocity != previous.velocity:
        if note.velocity != gp.Velocities.DEFAULT:
            flags |= 0x10
        # if note.isTiedNote or note.effect.deadNote:
        flags |= 0x20
        if note.effect.accentuatedNote:
            flags |= 0x40
        if note.effect.isFingering:
            flags |= 0x80

        self.writeByte(flags)

        if flags & 0x20 != 0:
            if note.isTiedNote:
                noteType = 0x02
            elif note.effect.deadNote:
                noteType = 0x03
            else:
                noteType = 0x01
            self.writeByte(noteType)
        
        if flags & 0x10 != 0:
            value = self.packVelocity(note.velocity)
            self.writeSignedByte(value)
        
        if flags & 0x20 != 0:
            fret = note.value if not note.isTiedNote else 0
            self.writeSignedByte(fret)
        
        if flags & 0x80 != 0:
            self.writeSignedByte(note.effect.leftHandFinger)
            self.writeSignedByte(note.effect.rightHandFinger)

        if flags & 0x01 != 0:
            self.writeDouble(note.durationPercent)
        
        flags2 = 0x00        
        if note.swapAccidentals:
            flags2 |= 0x02

        self.writeByte(flags2)
        
        if flags & 0x08 != 0:
            self.writeNoteEffects(note.effect)


    def writeNoteEffects(self, noteEffect):
        flags1 = 0x00
        if noteEffect.isBend():
            flags1 |= 0x01
        if noteEffect.hammer:
            flags1 |= 0x02
        if noteEffect.letRing:
            flags1 |= 0x08
        if noteEffect.isGrace():
            flags1 |= 0x10

        self.writeByte(flags1)

        flags2 = 0x00
        if noteEffect.staccato:
            flags2 |= 0x01
        if noteEffect.palmMute:
            flags2 |= 0x02
        if noteEffect.isTremoloPicking():
            flags2 |= 0x04
        if noteEffect.slide:
            flags2 |= 0x08
        if noteEffect.isHarmonic():
            flags2 |= 0x10
        if noteEffect.isTrill():
            flags2 |= 0x20
        if noteEffect.vibrato:
            flags2 |= 0x40

        self.writeByte(flags2)

        if flags1 & 0x01 != 0:
            self.writeBend(noteEffect.bend)
        if flags1 & 0x10 != 0:
            self.writeGrace(noteEffect.grace)
        if flags2 & 0x04 != 0:
            self.writeTremoloPicking(noteEffect.tremoloPicking)
        if flags2 & 0x08 != 0:
            self.writeByte(self.toSlideType(noteEffect.slide))            
        if flags2 & 0x10 != 0:
            self.writeArtificialHarmonic(noteEffect.harmonic)
        if flags2 & 0x20 != 0:
            self.writeTrill(noteEffect.trill)

    def toHarmonicType(self, harmonic):
        if harmonic.type == gp.HarmonicType.Natural:
            return 1
        elif harmonic.type == gp.HarmonicType.Artificial:
            self.skip(3) # Note?
            return 2
        elif harmonic.type == gp.HarmonicType.Tapped:
            self.skip(1) # Key?
            return 3
        elif harmonic.type == gp.HarmonicType.Pinch:
            return 4
        elif harmonic.type == gp.HarmonicType.Semi:
            return 5

    def writeGrace(self, grace):
        self.writeByte(grace.fret)
        self.writeByte(self.packVelocity(grace.velocity))
        self.writeByte(grace.transition)
        self.writeByte(grace.duration)

        flags = 0x00
        if grace.isDead:
            flags |= 0x01
        if grace.isOnBeat:
            flags |= 0x02

        self.writeByte(flags)

    def writeMixTableChange(self, tableChange):
        # self.writeSignedByte(tableChange.instrument.value)
        # self.placeholder(16, '\xff') # RSE info
        # self.writeSignedByte(tableChange.volume.value)
        # self.writeSignedByte(tableChange.balance.value)
        # self.writeSignedByte(tableChange.chorus.value)
        # self.writeSignedByte(tableChange.reverb.value)
        # self.writeSignedByte(tableChange.phaser.value)
        # self.writeSignedByte(tableChange.tremolo.value)
        # self.writeIntSizeCheckByteString(tableChange.tempoName)
        # self.writeInt(tableChange.tempo.value)
        
        items = [(tableChange.instrument, self.writeSignedByte),
                 ((16, '\xff'), self.placeholder), # RSE info
                 (tableChange.volume, self.writeSignedByte),
                 (tableChange.balance, self.writeSignedByte),
                 (tableChange.chorus, self.writeSignedByte),
                 (tableChange.reverb, self.writeSignedByte),
                 (tableChange.phaser, self.writeSignedByte),
                 (tableChange.tremolo, self.writeSignedByte),
                 (tableChange.tempoName, self.writeIntSizeCheckByteString),
                 (tableChange.tempo, self.writeInt)]

        for item, write in items:
            if isinstance(item, tuple):
                write(*item)
            elif isinstance(item, str):
                write(item)
            elif isinstance(item, gp.MixTableItem):
                write(item.value)
            else:
                write(-1)

        # instrument change doesn't have duration
        for item, write in items[2:]:
            if isinstance(item, gp.MixTableItem):
                write(item.duration)
                if hasattr(item, 'hideTempo'):
                    if tableChange.hideTempo and not self.version.endswith('5.00'):
                        self.writeBool(tableChange.hideTempo)

        allTracksFlags = 0x00
        for i, item in enumerate(items):
            if isinstance(item, gp.MixTableItem) and item.allTracks:
                allTracksFlags |= 1 << i

        self.writeByte(allTracksFlags)

        self.placeholder(1)
        if not self.version.endswith('5.00'):
            self.writeIntSizeCheckByteString(tableChange.skip1)
            self.writeIntSizeCheckByteString(tableChange.skip2)

    def writeChord(self, chord):
        self.placeholder(17)
        self.writeByteSizeString(chord.name, 21)
        self.placeholder(4)
        self.writeInt(chord.firstFret)
        for i in range(7):
            fret = -1
            if i < len(chord.strings):
                fret = chord.strings[i]
            self.writeInt(fret)
        self.placeholder(32)

    def writeMidiChannels(self, song):
        def getTrackChannelByChannel(channel):
            for track in song.tracks:
                if channel in (track.channel.channel, track.channel.effectChannel):
                    return track.channel
            default = gp.MidiChannel()
            default.channel = channel
            default.effectChannel = channel
            default.instrument = 0
            default.volume = 0
            default.balance = 0
            default.chorus = 0
            default.reverb = 0
            default.phaser = 0
            default.tremolo = 0
            return default

        for channel in map(getTrackChannelByChannel, range(64)):
            # if channel.isPercussionChannel() and channel.instrument == 0:
            #     self.writeInt(-1)
            # else:
            self.writeInt(channel.instrument)
            
            self.writeSignedByte(self.fromChannelShort(channel.volume))
            self.writeSignedByte(self.fromChannelShort(channel.balance))
            self.writeSignedByte(self.fromChannelShort(channel.chorus))
            self.writeSignedByte(self.fromChannelShort(channel.reverb))
            self.writeSignedByte(self.fromChannelShort(channel.phaser))
            self.writeSignedByte(self.fromChannelShort(channel.tremolo))
            # Backward compatibility with version 3.0
            self.placeholder(2)