ARG WORK_PATH=/keyboard
ARG PROJECT_NAME=absolem

FROM admwscki/kicad-kbplacer-primary:8.0.9-jammy

# this revision has been used when [1] has been written
# [1] https://adamws.github.io/keyboard-pcb-design-with-ergogen-and-kbplacer/
ARG KBPLACER_REVISION=ca69cbc0f1de216fd50f63ba26180ad683a91270

ARG KICAD_3RDPARTY_PATH=/root/.local/share/kicad/8.0/3rdparty
ARG WORK_PATH
ARG PROJECT_NAME

ARG SWITCH_LIBRARY=com_github_perigoso_keyswitch-kicad-library

RUN apt-get update \
  && apt-get install -y openscad xdotool x11-xserver-utils x11-apps zip

ENV DISPLAY=:99
ENV XAUTHORITY=/root/.Xauthority

RUN touch $XAUTHORITY && chmod 600 $XAUTHORITY

# install 3rdparty footprints
RUN mkdir -p $KICAD_3RDPARTY_PATH
RUN cd $KICAD_3RDPARTY_PATH \
  && mkdir -p footprints \
  && mkdir tmp && cd tmp \
  && wget https://github.com/kiswitch/keyswitch-kicad-library/releases/download/v2.4/keyswitch-kicad-library.zip \
  && echo "b38d56323acb91ad660567340ca938c5b4a83a27eea52308ef14aa7857b0071b keyswitch-kicad-library.zip" | sha256sum -c \
  && unzip keyswitch-kicad-library.zip \
  && rm keyswitch-kicad-library.zip \
  && mv footprints ../footprints/$SWITCH_LIBRARY \
  && cd .. && rm -rf tmp

RUN python3 -m pip install hatch PyYAML==6.0.1
RUN git clone https://github.com/adamws/kicad-kbplacer.git \
  && cd kicad-kbplacer \
  && git checkout $KBPLACER_REVISION \
  && python3 -m pip install .

RUN mkdir -p $WORK_PATH
COPY points.yaml $WORK_PATH

WORKDIR $WORK_PATH

COPY template.kicad_pro $WORK_PATH/$PROJECT_NAME.kicad_pro
RUN sed -i 's/template\.kicad_pro/$PROJECT_NAME\.kicad_pro/g' $PROJECT_NAME.kicad_pro

RUN python3 -m kbplacer.kle_serial \
  -in points.yaml -inform ERGOGEN_INTERNAL \
  -outform KLE_RAW -out $PROJECT_NAME-kle.json

# fix labels (to be fixed in kbplacer)
RUN sed -i 's/[RC]//g' $PROJECT_NAME-kle.json

RUN cd /kicad-kbplacer \
  && hatch run tools:layout2schematic -in $WORK_PATH/$PROJECT_NAME-kle.json \
  -out $WORK_PATH/$PROJECT_NAME.kicad_sch -f \
  -swf "Switch_Keyboard_Cherry_MX:SW_Cherry_MX_PCB_1.00u" \
  -df "Diode_SMD:D_SOD-123F"

# this is required, otherwise netlist will contain many 'unconnected' pads
COPY eeschema-open-and-save.sh $WORK_PATH
RUN xvfb-run ./eeschema-open-and-save.sh $PROJECT_NAME.kicad_sch

RUN kicad-cli sch export netlist --output $PROJECT_NAME.net $PROJECT_NAME.kicad_sch
RUN python3 -m pip install kinet2pcb==1.1.2
RUN kinet2pcb -i $PROJECT_NAME.net \
  --libraries /usr/share/kicad/footprints \
              $KICAD_3RDPARTY_PATH/footprints/$SWITCH_LIBRARY/Switch_Keyboard_Cherry_MX.pretty \
  --output $PROJECT_NAME.kicad_pcb

RUN python3 -m kbplacer --board $PROJECT_NAME.kicad_pcb \
  --layout $PROJECT_NAME-kle.json \
  --diode "D{} CUSTOM 5.08 4 90 BACK" \
  --route-switches-with-diodes \
  --route-rows-and-columns

RUN kicad-cli pcb export svg --exclude-drawing-sheet \
  -l F.Cu,B.Cu,F.Silkscreen -o $PROJECT_NAME.svg $PROJECT_NAME.kicad_pcb

RUN zip -r $PROJECT_NAME.zip \
  $PROJECT_NAME-kle.json \
  $PROJECT_NAME.kicad_pro \
  $PROJECT_NAME.kicad_sch \
  $PROJECT_NAME.kicad_pcb \
  $PROJECT_NAME.net \
  $PROJECT_NAME.svg

# sanity check for plate generation tool
COPY generate-plate.sh $WORK_PATH
RUN xvfb-run -a ./generate-plate.sh $KBPLACER_REVISION

FROM scratch
ARG WORK_PATH
ARG PROJECT_NAME
COPY --from=0 $WORK_PATH/$PROJECT_NAME.zip .
